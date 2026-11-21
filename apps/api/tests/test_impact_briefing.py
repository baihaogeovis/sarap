"""Published one-map and the default briefing expose impact stats and hide drafts."""

from __future__ import annotations

from pyproj import Transformer

from tests.conftest import admin_headers, demo_ids, duty_headers, readonly_headers

INTERNAL = {"X-Internal-Token": "test-internal-token"}


def _line(area, lon0, lat0, lon1, lat1, name: str):
    transformer = Transformer.from_crs("EPSG:4326", area.analysis_crs, always_xy=True)
    xs, ys = transformer.transform([lon0, lon1], [lat0, lat1])
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"name": name, "object_type": "road", "object_id": name, "affected": True},
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[float(xs[0]), float(ys[0])], [float(xs[1]), float(ys[1])]],
                },
            }
        ],
    }


def _water(area):
    transformer = Transformer.from_crs("EPSG:4326", area.analysis_crs, always_xy=True)
    corners = [(116.40, 39.80), (116.42, 39.80), (116.42, 39.82), (116.40, 39.82), (116.40, 39.80)]
    xs, ys = transformer.transform([p[0] for p in corners], [p[1] for p in corners])
    ring = [[float(x), float(y)] for x, y in zip(xs, ys, strict=True)]
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"class_code": 5, "name": "提取水体"},
                "geometry": {"type": "Polygon", "coordinates": [ring]},
            }
        ],
    }


def _impact(name: str, length: float):
    return {
        "cross_stats": [
            {
                "object_type": "road",
                "object_id": name,
                "object_name": name,
                "metric": "affected_length_m",
                "value": length,
                "unit": "m",
                "scope": "default",
                "extra": {"basis": "extracted_water", "parent_admin_code": ""},
            },
            {
                "object_type": "settlement",
                "object_id": "st-1",
                "object_name": "临水居民点",
                "metric": "affected_area_ha",
                "value": 1.25,
                "unit": "ha",
                "scope": "default",
                "extra": {"parent_admin_code": ""},
            },
            {
                "object_type": "admin_county",
                "object_id": "county-west",
                "object_name": "开阔水体县",
                "metric": "affected_area_ha",
                "value": 4.5,
                "unit": "ha",
                "scope": "default",
                "extra": {"parent_admin_code": ""},
            },
        ],
        "limitation": "统计基于雷达提取范围，建成区可能低估，不含水深和人口。",
    }


def _create(client, headers, project, area, *, title, road_name, length):
    return client.post(
        "/api/v1/products",
        headers=headers,
        json={
            "project_id": str(project.id),
            "area_id": str(area.id),
            "scene_code": "flood",
            "product_type": "SARAP_FLOOD_V1",
            "title": title,
            "extracted_water_ha": 6.5,
            "metadata_json": {"crs": area.analysis_crs},
            "artifacts_json": [
                {
                    "layer_key": "water_current_poly",
                    "media_type": "application/geo+json",
                    "storage_uri": "file:///water.geojson",
                    "metadata_json": {"crs": area.analysis_crs, "geojson": _water(area)},
                },
                {
                    "layer_key": "impact_road",
                    "media_type": "application/geo+json",
                    "storage_uri": "file:///road.geojson",
                    "metadata_json": {"crs": area.analysis_crs, "geojson": _line(area, 116.40, 39.80, 116.43, 39.83, road_name)},
                },
                {
                    "layer_key": "impact_stats",
                    "media_type": "application/json",
                    "storage_uri": "file:///impact_stats.json",
                    "metadata_json": {"document": _impact(road_name, length)},
                },
            ],
        },
    )


def test_default_map_and_briefing_use_published_impact_only(client, db):
    duty = duty_headers(client)
    admin = admin_headers(client)
    ro = readonly_headers(client)
    _, project, area = demo_ids(db)

    preview = client.get(
        "/api/v1/briefings/preview",
        params={"project_id": str(project.id), "area_id": str(area.id)},
        headers=ro,
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["data"]["empty"] is True
    assert preview.json()["data"]["layers"] == []
    assert preview.json()["data"]["area"]["aoi"]["features"]

    published = _create(client, duty, project, area, title="已发布水体", road_name="已发布道路", length=320)
    assert published.status_code == 201, published.text
    published_id = published.json()["data"]["id"]
    draft = _create(client, duty, project, area, title="草稿水体", road_name="草稿道路", length=999)
    assert draft.status_code == 201, draft.text
    draft_id = draft.json()["data"]["id"]

    stats = client.get(f"/api/v1/products/{published_id}/stats", headers=duty)
    assert stats.status_code == 200, stats.text
    names = {row["object_name"] for row in stats.json()["data"]}
    assert "已发布道路" in names
    assert "临水居民点" in names
    assert "开阔水体县" in names
    assert client.get(f"/api/v1/products/{draft_id}/stats", headers=ro).status_code == 404

    assert client.post(f"/api/v1/products/{published_id}/publish", json={}, headers=duty).status_code == 200

    mapped = client.get(
        "/api/v1/products/map",
        params={"area_id": str(area.id), "project_id": str(project.id)},
        headers=ro,
    )
    assert mapped.status_code == 200, mapped.text
    body = mapped.json()["data"]
    ids = {item["id"] for item in body["products"]}
    assert published_id in ids
    assert draft_id not in ids
    shown = next(item for item in body["products"] if item["id"] == published_id)
    kinds = {layer["kind"] for layer in shown["layers"]}
    assert "water" in kinds
    assert "road" in kinds
    road = next(layer for layer in shown["layers"] if layer["kind"] == "road")
    blob = str(road)
    assert "已发布道路" in blob
    assert "草稿道路" not in str(body)
    xs = []
    for feature in road["geojson"]["features"]:
        for pt in feature["geometry"]["coordinates"]:
            xs.append(pt[0])
    assert all(-180 <= x <= 180 for x in xs)
    assert shown["impact"]["impact_configured"] is True
    assert shown["impact"]["affected_road_count"] == 1
    assert shown["impact"]["affected_road_length_m"] == 320
    assert shown["impact"]["affected_settlement_count"] == 1
    assert shown["impact"]["affected_admin_count"] == 1
    assert shown["flood_event_status"] == "baseline_missing"
    assert shown["layers"][0]["title"] != "本次淹没"

    viewed = client.get(
        "/api/v1/briefings/preview",
        params={"project_id": str(project.id), "area_id": str(area.id), "scene_code": "flood"},
        headers=ro,
    )
    assert viewed.status_code == 200, viewed.text
    doc = viewed.json()["data"]
    assert doc["empty"] is False
    assert doc["product"]["id"] == published_id
    assert "草稿道路" not in str(doc)
    assert "已发布道路" in str(doc)
    assert doc["stats"]["affected_road_length_m"] == 320
    assert "本次淹没" not in doc["basis_label"]
    assert "提取水体" in doc["conclusion"]
    assert doc["stats"]["inundation_ha"] == 6.5

    blocked = client.post(
        "/api/v1/briefings",
        headers=duty,
        json={
            "project_id": str(project.id),
            "scene_code": "flood",
            "title": "引用草稿",
            "content_json": {"summary": "不应发布"},
            "product_ids": [draft_id],
        },
    )
    assert blocked.status_code == 201, blocked.text
    blocked_id = blocked.json()["data"]["id"]
    denied = client.post(f"/api/v1/briefings/{blocked_id}/publish", headers=admin)
    assert denied.status_code == 409
    assert denied.json()["error"]["code"] == "unpublished_product"

    saved = client.post(
        "/api/v1/briefings",
        headers=duty,
        json={
            "project_id": str(project.id),
            "scene_code": "flood",
            "title": "已发布简报",
            "content_json": {"conclusion": "值班结论：只通报已发布范围。"},
            "product_ids": [published_id],
        },
    )
    assert saved.status_code == 201, saved.text
    briefing_id = saved.json()["data"]["id"]
    assert client.post(f"/api/v1/briefings/{briefing_id}/publish", headers=admin).status_code == 200
    rendered = client.get(f"/api/v1/briefings/{briefing_id}/document", headers=ro)
    assert rendered.status_code == 200, rendered.text
    page = rendered.json()["data"]
    assert page["empty"] is False
    assert page["conclusion"] == "值班结论：只通报已发布范围。"
    assert page["stats"]["affected_settlement_area_ha"] == 1.25
    assert "草稿" not in str(page["layers"])

    assert client.post(
        f"/api/v1/products/{published_id}/withdraw",
        json={"reason": "撤"},
        headers=admin,
    ).status_code == 200
    after = client.get(f"/api/v1/briefings/{briefing_id}/document", headers=ro)
    assert after.status_code == 200, after.text
    assert after.json()["data"]["empty"] is True
    assert after.json()["data"]["layers"] == []
    again = client.get(
        "/api/v1/products/map",
        params={"area_id": str(area.id)},
        headers=ro,
    )
    assert published_id not in {item["id"] for item in again.json()["data"]["products"]}


def test_startup_restores_missing_demo_fixture_without_clobbering_a_custom_road(db):
    from app.services.seed import _ensure_demo_impact_assets

    _, _, area = demo_ids(db)
    config = dict(area.config_json or {})
    config.pop("impact_assets", None)
    area.config_json = config
    db.commit()
    _ensure_demo_impact_assets(db)
    db.commit()
    db.refresh(area)
    assert area.config_json["impact_assets"]["road"] == "fixture:public_validation_window"

    custom = dict(area.config_json)
    custom["impact_assets"] = {"road": "file:///custom.geojson"}
    area.config_json = custom
    db.commit()
    _ensure_demo_impact_assets(db)
    db.refresh(area)
    assert area.config_json["impact_assets"]["road"] == "file:///custom.geojson"


def test_dispatch_sends_public_validation_fixture(client, db, engine_client):
    duty = duty_headers(client)
    _, project, area = demo_ids(db)
    created = client.post(
        "/api/v1/tasks",
        headers=duty,
        json={
            "project_id": str(project.id),
            "area_id": str(area.id),
            "scene_code": "flood",
            "task_type": "flood_pipeline",
            "title": "带影响对象的 mock 任务",
            "s1_product_id": "S1A_IW_GRDH_1SDV_20260701T100000_IMPACT",
            "acquisition_start": "2026-07-01T10:00:00Z",
        },
    )
    assert created.status_code == 201, created.text
    payload = next(iter(engine_client.jobs.values()))["payload"]
    assets = payload["pilot"]["impact_assets"]
    assert assets["road"] == "fixture:public_validation_window"
    assert assets["settlement"] == "fixture:public_validation_window"
    assert assets["admin_county"] == "fixture:public_validation_window"
    assert "长江" not in str(payload)
    assert "滨江" not in str(payload)


def test_internal_ingest_stores_cross_stats(client, db):
    duty = duty_headers(client)
    _, project, area = demo_ids(db)
    task = client.post(
        "/api/v1/tasks",
        headers=duty,
        json={
            "project_id": str(project.id),
            "area_id": str(area.id),
            "scene_code": "flood",
            "task_type": "flood_pipeline",
            "title": "入库交叉统计",
            "s1_product_id": "S1A_IW_GRDH_1SDV_20260701T100000_STATS",
            "acquisition_start": "2026-07-01T10:00:00Z",
        },
    )
    assert task.status_code == 201, task.text
    ingest = client.post(
        "/api/v1/internal/products",
        headers=INTERNAL,
        json={
            "task_id": task.json()["data"]["id"],
            "product_type": "SARAP_FLOOD_V1",
            "title": "mock 影响统计",
            "extracted_water_ha": 2.5,
            "impact_stats": _impact("穿水道路", 410),
            "metadata_json": {"crs": area.analysis_crs, "mock": True},
        },
    )
    assert ingest.status_code == 201, ingest.text
    product_id = ingest.json()["data"]["id"]
    assert ingest.json()["data"]["status"] == "draft"
    stats = client.get(f"/api/v1/products/{product_id}/stats", headers=duty)
    assert stats.status_code == 200, stats.text
    road = next(row for row in stats.json()["data"] if row["metric"] == "affected_length_m")
    assert road["value"] == 410
    assert road["object_type"] == "road"
    assert road["extra_json"]["basis"] == "extracted_water"
