"""Default one-map serves published vectors in lon/lat and hides everything else."""

from __future__ import annotations

from pyproj import Transformer

from tests.conftest import admin_headers, demo_ids, duty_headers, readonly_headers


def _ring(area, lon0, lat0, lon1, lat1, *, class_code: int):
    transformer = Transformer.from_crs("EPSG:4326", area.analysis_crs, always_xy=True)
    corners = [(lon0, lat0), (lon1, lat0), (lon1, lat1), (lon0, lat1), (lon0, lat0)]
    xs, ys = transformer.transform([p[0] for p in corners], [p[1] for p in corners])
    ring = [[float(x), float(y)] for x, y in zip(xs, ys, strict=True)]
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"class_code": class_code, "area_ha": 1.25},
                "geometry": {"type": "Polygon", "coordinates": [ring]},
            }
        ],
    }


def _bounds(collection):
    xs: list[float] = []
    ys: list[float] = []

    def walk(coords):
        if isinstance(coords, list) and coords and isinstance(coords[0], (int, float)):
            xs.append(float(coords[0]))
            ys.append(float(coords[1]))
            return
        if isinstance(coords, list):
            for item in coords:
                walk(item)

    for feature in collection.get("features") or []:
        walk((feature.get("geometry") or {}).get("coordinates"))
    return min(xs), min(ys), max(xs), max(ys)


def _create(client, headers, project, area, *, title, geojson, layer_key="water_current_poly", class_code=5, scene_code="flood"):
    return client.post(
        "/api/v1/products",
        json={
            "project_id": str(project.id),
            "area_id": str(area.id),
            "scene_code": scene_code,
            "product_type": "SARAP_FLOOD_V1",
            "title": title,
            "extracted_water_ha": 4.5,
            "metadata_json": {"crs": area.analysis_crs},
            "artifacts_json": [
                {
                    "layer_key": layer_key,
                    "media_type": "application/geo+json",
                    "storage_uri": f"file:///{layer_key}.geojson",
                    "metadata_json": {"crs": area.analysis_crs, "geojson": geojson},
                }
            ],
        },
        headers=headers,
    )


def test_map_reprojects_published_layer_and_hides_the_rest(client, db):
    duty = duty_headers(client)
    admin = admin_headers(client)
    ro = readonly_headers(client)
    _, project, area = demo_ids(db)
    published_geo = _ring(area, 116.40, 39.80, 116.42, 39.82, class_code=5)
    draft_geo = _ring(area, 116.55, 39.90, 116.57, 39.92, class_code=5)

    published = _create(client, duty, project, area, title="已发布范围", geojson=published_geo)
    assert published.status_code == 201, published.text
    published_id = published.json()["data"]["id"]
    assert client.post(f"/api/v1/products/{published_id}/publish", json={}, headers=duty).status_code == 200

    draft = _create(client, duty, project, area, title="草稿范围", geojson=draft_geo)
    assert draft.status_code == 201, draft.text
    draft_id = draft.json()["data"]["id"]

    pending = _create(client, duty, project, area, title="待质检范围", geojson=draft_geo)
    pending_id = pending.json()["data"]["id"]
    assert client.post(f"/api/v1/products/{pending_id}/submit", json={}, headers=duty).status_code == 200

    withdrawn = _create(client, duty, project, area, title="已撤回范围", geojson=draft_geo)
    withdrawn_id = withdrawn.json()["data"]["id"]
    assert client.post(f"/api/v1/products/{withdrawn_id}/publish", json={}, headers=duty).status_code == 200
    assert client.post(
        f"/api/v1/products/{withdrawn_id}/withdraw",
        json={"reason": "撤"},
        headers=admin,
    ).status_code == 200

    bare = client.post(
        "/api/v1/products",
        json={
            "project_id": str(project.id),
            "area_id": str(area.id),
            "scene_code": "flood",
            "product_type": "SARAP_FLOOD_V1",
            "title": "无矢量",
            "extracted_water_ha": 1,
            "artifacts_json": [{"layer_key": "class_map", "media_type": "image/tiff", "storage_uri": "file://class.tif"}],
        },
        headers=duty,
    )
    assert bare.status_code == 201, bare.text
    bare_id = bare.json()["data"]["id"]
    assert client.post(f"/api/v1/products/{bare_id}/publish", json={}, headers=duty).status_code == 200

    mapped = client.get(
        "/api/v1/products/map",
        params={"area_id": str(area.id), "project_id": str(project.id), "scene_code": "flood"},
        headers=ro,
    )
    assert mapped.status_code == 200, mapped.text
    body = mapped.json()["data"]
    assert body["area"]["analysis_crs"] == area.analysis_crs
    assert body["area"]["aoi"]["features"]
    assert body["area"]["aoi"]["features"][0]["properties"]["role"] == "aoi"
    ids = {item["id"] for item in body["products"]}
    assert published_id in ids
    assert bare_id in ids
    assert draft_id not in ids
    assert pending_id not in ids
    assert withdrawn_id not in ids

    shown = next(item for item in body["products"] if item["id"] == published_id)
    assert shown["status"] == "published"
    assert shown["flood_event_status"] == "baseline_missing"
    assert len(shown["layers"]) == 1
    layer = shown["layers"][0]
    assert layer["title"] == "提取水体（未扣本底）"
    assert layer["kind"] == "water"
    assert layer["title"] != "本次淹没"
    minx, miny, maxx, maxy = _bounds(layer["geojson"])
    assert 116.39 <= minx <= 116.43
    assert 116.39 <= maxx <= 116.43
    assert 39.79 <= miny <= 39.83
    assert 39.79 <= maxy <= 39.83
    # The outline is the area, not a stand-in flood polygon.
    aoi_minx, _, aoi_maxx, _ = _bounds(body["area"]["aoi"])
    assert (maxx - minx) < (aoi_maxx - aoi_minx) / 2

    bare_row = next(item for item in body["products"] if item["id"] == bare_id)
    assert bare_row["layers"] == []

    hidden = client.get(f"/api/v1/products/{draft_id}/layers/water_current_poly", headers=ro)
    assert hidden.status_code == 404
    opened = client.get(f"/api/v1/products/{draft_id}/layers/water_current_poly", headers=duty)
    assert opened.status_code == 200, opened.text
    assert opened.json()["data"]["features"]

    visible = client.get(f"/api/v1/products/{published_id}/layers/water_current_poly", headers=ro)
    assert visible.status_code == 200, visible.text
    assert visible.json()["meta"]["crs"] == "EPSG:4326"
    assert visible.json()["meta"]["source_crs"] == area.analysis_crs


def _publish_baseline(client, admin, project, area) -> str:
    asset = client.post(
        "/api/v1/data-assets",
        headers=admin,
        json={
            "asset_code": "PERM_MAP",
            "name": "常年水体",
            "asset_type": "permanent_water",
            "project_id": str(project.id),
            "area_id": str(area.id),
            "default_crs": area.analysis_crs,
        },
    )
    assert asset.status_code == 201, asset.text
    version = client.post(
        f"/api/v1/data-assets/{asset.json()['data']['id']}/versions",
        headers=admin,
        json={
            "version_no": "v-map",
            "crs": area.analysis_crs,
            "storage_uri": "file:///baselines/permanent.tif",
            "applicable_area_name": area.name,
        },
    )
    assert version.status_code == 201, version.text
    version_id = version.json()["data"]["id"]
    published = client.post(f"/api/v1/data-asset-versions/{version_id}/publish", headers=admin, json={})
    assert published.status_code == 200, published.text
    return version_id


def test_computed_product_shows_inundation_separate_from_baseline(client, db):
    duty = duty_headers(client)
    admin = admin_headers(client)
    _, project, area = demo_ids(db)
    version_id = _publish_baseline(client, admin, project, area)
    event = _ring(area, 116.45, 39.85, 116.47, 39.87, class_code=3)
    baseline = _ring(area, 116.30, 39.70, 116.33, 39.73, class_code=2)
    current = {"type": "FeatureCollection", "features": baseline["features"] + event["features"]}
    created = client.post(
        "/api/v1/products",
        json={
            "project_id": str(project.id),
            "area_id": str(area.id),
            "scene_code": "flood",
            "product_type": "SARAP_FLOOD_V1",
            "title": "有本底淹没",
            "baseline_version_id": version_id,
            "water_current_ha": 3.2,
            "flood_event_ha": 1.1,
            "artifacts_json": [
                {
                    "layer_key": "water_current_poly",
                    "media_type": "application/geo+json",
                    "storage_uri": "file:///water_current_poly.geojson",
                    "metadata_json": {"crs": area.analysis_crs, "geojson": current},
                },
                {
                    "layer_key": "flood_event_poly",
                    "media_type": "application/geo+json",
                    "storage_uri": "file:///flood_event_poly.geojson",
                    "metadata_json": {"crs": area.analysis_crs, "geojson": event},
                },
            ],
        },
        headers=duty,
    )
    assert created.status_code == 201, created.text
    product = created.json()["data"]
    assert product["flood_event_status"] == "computed"
    assert product["suggested_target_minutes"] == 240
    product_id = product["id"]
    assert client.post(f"/api/v1/products/{product_id}/publish", json={}, headers=duty).status_code == 200

    mapped = client.get("/api/v1/products/map", params={"area_id": str(area.id)}, headers=duty)
    assert mapped.status_code == 200, mapped.text
    shown = next(item for item in mapped.json()["data"]["products"] if item["id"] == product_id)
    by_kind = {layer["kind"]: layer for layer in shown["layers"]}
    assert by_kind["event"]["title"] == "本次淹没"
    assert by_kind["baseline"]["title"] == "本底水体"
    emin, _, emax, _ = _bounds(by_kind["event"]["geojson"])
    assert 116.44 <= emin and emax <= 116.48
    bmin, _, bmax, _ = _bounds(by_kind["baseline"]["geojson"])
    assert 116.29 <= bmin and bmax <= 116.34
    # Class 3 stays on the inundation layer.
    assert all(feature["properties"]["class_code"] == 3 for feature in by_kind["event"]["geojson"]["features"])
    assert all(feature["properties"]["class_code"] == 2 for feature in by_kind["baseline"]["geojson"]["features"])
