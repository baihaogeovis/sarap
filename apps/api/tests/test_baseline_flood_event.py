"""Publish a baseline, cite it on a flood task, and show 本次淹没 on the defaults.

The hectare figures are the mock change-detection result locked in
engine/tests/test_demo_baseline_change.py. This test checks that the platform
only accepts a published baseline_version_id and that the default map and
briefing keep that citation.
"""

from __future__ import annotations

from pyproj import Transformer

from tests.conftest import admin_headers, demo_ids, duty_headers, readonly_headers

INTERNAL = {"X-Internal-Token": "test-internal-token"}

# Confident flood minus the synthetic permanent-water baseline on the 800 m window.
FLOOD_EVENT_HA = 6.75
WATER_CURRENT_HA = 17.75
ROAD_M = 301
SETTLEMENT_HA = 0.79
ADMIN_HA = 9.9


def _ring(area, lon0, lat0, lon1, lat1, *, class_code: int, name: str):
    transformer = Transformer.from_crs("EPSG:4326", area.analysis_crs, always_xy=True)
    corners = [(lon0, lat0), (lon1, lat0), (lon1, lat1), (lon0, lat1), (lon0, lat0)]
    xs, ys = transformer.transform([p[0] for p in corners], [p[1] for p in corners])
    ring = [[float(x), float(y)] for x, y in zip(xs, ys, strict=True)]
    return {
        "type": "Feature",
        "properties": {"class_code": class_code, "name": name},
        "geometry": {"type": "Polygon", "coordinates": [ring]},
    }


def _collection(*features):
    return {"type": "FeatureCollection", "features": list(features)}


def _publish_baseline(client, admin, project, area, *, code: str, version_no: str, storage_uri: str = "") -> str:
    asset = client.post(
        "/api/v1/data-assets",
        headers=admin,
        json={
            "asset_code": code,
            "name": "演示常年水体",
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
            "version_no": version_no,
            "crs": area.analysis_crs,
            "storage_uri": storage_uri,
            "applicable_area_name": area.name,
            "applicable_area_geojson": area.aoi_geojson,
            "source": "mock" if not storage_uri else "staged",
        },
    )
    assert version.status_code == 201, version.text
    version_id = version.json()["data"]["id"]
    published = client.post(f"/api/v1/data-asset-versions/{version_id}/publish", headers=admin, json={})
    assert published.status_code == 200, published.text
    assert published.json()["data"]["review_status"] == "published"
    return version_id


def test_duty_cannot_publish_a_baseline(client, db):
    duty = duty_headers(client)
    _, project, area = demo_ids(db)
    denied = client.post(
        "/api/v1/data-assets",
        headers=duty,
        json={
            "asset_code": "DUTY_BASE",
            "name": "值班员本底",
            "asset_type": "permanent_water",
            "project_id": str(project.id),
            "area_id": str(area.id),
            "default_crs": area.analysis_crs,
        },
    )
    assert denied.status_code == 403


def test_unpublished_baseline_is_rejected_and_empty_uri_is_not_a_raster(client, db, engine_client):
    admin = admin_headers(client)
    duty = duty_headers(client)
    _, project, area = demo_ids(db)
    asset = client.post(
        "/api/v1/data-assets",
        headers=admin,
        json={
            "asset_code": "DRAFT_BASE",
            "name": "未发布本底",
            "asset_type": "permanent_water",
            "project_id": str(project.id),
            "area_id": str(area.id),
            "default_crs": area.analysis_crs,
        },
    )
    assert asset.status_code == 201, asset.text
    draft = client.post(
        f"/api/v1/data-assets/{asset.json()['data']['id']}/versions",
        headers=admin,
        json={
            "version_no": "v-draft",
            "crs": area.analysis_crs,
            "applicable_area_name": area.name,
            "applicable_area_geojson": area.aoi_geojson,
            "source": "mock",
        },
    )
    assert draft.status_code == 201, draft.text
    draft_id = draft.json()["data"]["id"]
    rejected = client.post(
        "/api/v1/tasks",
        headers=duty,
        json={
            "project_id": str(project.id),
            "area_id": str(area.id),
            "scene_code": "flood",
            "task_type": "flood_pipeline",
            "title": "引用草稿本底",
            "baseline_version_id": draft_id,
            "s1_product_id": "S1A_IW_GRDH_1SDV_20260701T100000_DRAFT",
            "acquisition_start": "2026-07-01T10:00:00Z",
        },
    )
    assert rejected.status_code == 409, rejected.text
    assert rejected.json()["error"]["code"] == "BASELINE_NOT_PUBLISHED"

    version_id = _publish_baseline(client, admin, project, area, code="PERM_EMPTY", version_no="v1")
    created = client.post(
        "/api/v1/tasks",
        headers=duty,
        json={
            "project_id": str(project.id),
            "area_id": str(area.id),
            "scene_code": "flood",
            "task_type": "flood_pipeline",
            "title": "引用已发布本底",
            "baseline_version_id": version_id,
            "s1_product_id": "S1A_IW_GRDH_1SDV_20260701T100000_DEMO",
            "acquisition_start": "2026-07-01T10:00:00Z",
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["data"]["baseline_version_id"] == version_id
    payload = next(iter(engine_client.jobs.values()))["payload"]
    assert payload["baseline_version_id"] == version_id
    assert not payload.get("baseline_uri")


def test_conflicting_published_versions_fail_unless_preferred(client, db):
    admin = admin_headers(client)
    duty = duty_headers(client)
    _, project, area = demo_ids(db)
    first = _publish_baseline(client, admin, project, area, code="PERM_A", version_no="v1")
    second = _publish_baseline(client, admin, project, area, code="PERM_B", version_no="v1")
    conflict = client.post(
        "/api/v1/tasks",
        headers=duty,
        json={
            "project_id": str(project.id),
            "area_id": str(area.id),
            "scene_code": "flood",
            "task_type": "flood_pipeline",
            "title": "两个已发布本底",
            "s1_product_id": "S1A_IW_GRDH_1SDV_20260701T100000_CONF",
            "acquisition_start": "2026-07-01T10:00:00Z",
        },
    )
    assert conflict.status_code == 409, conflict.text
    assert conflict.json()["error"]["code"] == "BASELINE_VERSION_CONFLICT"

    config = dict(area.config_json or {})
    baselines = dict(config.get("baselines") or {})
    baselines["preferred_version_id"] = second
    config["baselines"] = baselines
    patched = client.patch(
        f"/api/v1/areas/{area.id}",
        headers=admin,
        json={
            "code": area.code,
            "name": area.name,
            "is_pilot": True,
            "analysis_crs": area.analysis_crs,
            "exchange_crs": area.exchange_crs,
            "grid_res_m": area.grid_res_m,
            "aoi_geojson": area.aoi_geojson,
            "config_json": config,
        },
    )
    assert patched.status_code == 200, patched.text
    chosen = client.post(
        "/api/v1/tasks",
        headers=duty,
        json={
            "project_id": str(project.id),
            "area_id": str(area.id),
            "scene_code": "flood",
            "task_type": "flood_pipeline",
            "title": "preferred 选定本底",
            "s1_product_id": "S1A_IW_GRDH_1SDV_20260701T100000_PREF",
            "acquisition_start": "2026-07-01T10:00:00Z",
        },
    )
    assert chosen.status_code == 201, chosen.text
    assert chosen.json()["data"]["baseline_version_id"] == second
    assert chosen.json()["data"]["baseline_version_id"] != first


def test_published_flood_product_defaults_to_inundation(client, db):
    admin = admin_headers(client)
    duty = duty_headers(client)
    ro = readonly_headers(client)
    _, project, area = demo_ids(db)
    # Capture the no-baseline contrast before a published version exists.
    # Afterwards a unique published baseline is auto-bound even if the form leaves it blank.
    missing = client.post(
        "/api/v1/tasks",
        headers=duty,
        json={
            "project_id": str(project.id),
            "area_id": str(area.id),
            "scene_code": "flood",
            "task_type": "flood_pipeline",
            "title": "无本底对照",
            "s1_product_id": "S1A_IW_GRDH_1SDV_20260701T100000_NONE",
            "acquisition_start": "2026-07-01T10:00:00Z",
        },
    )
    assert missing.status_code == 201, missing.text
    assert missing.json()["data"]["baseline_version_id"] is None

    version_id = _publish_baseline(client, admin, project, area, code="PERM_MAP", version_no="v1")
    created = client.post(
        "/api/v1/tasks",
        headers=duty,
        json={
            "project_id": str(project.id),
            "area_id": str(area.id),
            "scene_code": "flood",
            "task_type": "flood_pipeline",
            "title": "对照已发布本底",
            "baseline_version_id": version_id,
            "s1_product_id": "S1A_IW_GRDH_1SDV_20260701T100000_DEMO",
            "acquisition_start": "2026-07-01T10:00:00Z",
            "acquisition_end": "2026-07-01T10:00:25Z",
        },
    )
    assert created.status_code == 201, created.text
    task_id = created.json()["data"]["id"]

    event = _ring(area, 116.40, 39.90, 116.42, 39.92, class_code=3, name="本次淹没")
    baseline = _ring(area, 116.35, 39.88, 116.38, 39.91, class_code=2, name="本底水体")
    def _cross(object_type, object_id, name, metric, value, unit):
        return {
            "object_type": object_type,
            "object_id": object_id,
            "object_name": name,
            "metric": metric,
            "value": value,
            "unit": unit,
            "scope": "default",
            "extra": {
                "basis": "flood_event",
                "baseline_version_id": version_id,
                "parent_admin_code": "",
            },
        }

    ingested = client.post(
        "/api/v1/internal/products",
        headers=INTERNAL,
        json={
            "task_id": task_id,
            "product_type": "SARAP_FLOOD_V1",
            "title": "示例区域洪水淹没范围（Sentinel-1）",
            "baseline_version_id": version_id,
            "water_current_ha": WATER_CURRENT_HA,
            "flood_event_ha": FLOOD_EVENT_HA,
            "lowconf_ha": 4.75,
            "s1_product_id": "S1A_IW_GRDH_1SDV_20260701T100000_DEMO",
            "acquisition_start": "2026-07-01T10:00:00Z",
            "metadata_json": {"crs": area.analysis_crs, "mock": True},
            "artifacts_json": [
                {
                    "layer_key": "water_current_poly",
                    "media_type": "application/geo+json",
                    "storage_uri": "file:///water_current_poly.geojson",
                    "metadata_json": {
                        "crs": area.analysis_crs,
                        "geojson": _collection(baseline, event),
                    },
                },
                {
                    "layer_key": "flood_event_poly",
                    "media_type": "application/geo+json",
                    "storage_uri": "file:///flood_event_poly.geojson",
                    "metadata_json": {
                        "crs": area.analysis_crs,
                        "geojson": _collection(event),
                    },
                },
            ],
            "impact_stats": {
                "cross_stats": [
                    _cross("road", "rd-cross", "穿水道路", "affected_length_m", ROAD_M, "m"),
                    _cross("settlement", "st-flood", "临水居民点", "affected_area_ha", SETTLEMENT_HA, "ha"),
                    _cross("admin_county", "county-west", "开阔水体县", "affected_area_ha", 6.75, "ha"),
                    _cross("admin_township", "township-river", "沿水乡镇", "affected_area_ha", 3.15, "ha"),
                ]
            },
        },
    )
    assert ingested.status_code == 201, ingested.text
    product = ingested.json()["data"]
    assert product["status"] == "draft"
    assert product["flood_event_status"] == "computed"
    assert product["flood_event_ha"] == FLOOD_EVENT_HA
    assert product["water_current_ha"] == WATER_CURRENT_HA
    assert product["baseline_version_id"] == version_id
    assert product["baseline_version"] == "v1"
    assert product["extracted_water_ha"] is None
    product_id = product["id"]

    hidden = client.get(
        "/api/v1/products/map",
        params={"area_id": str(area.id), "project_id": str(project.id)},
        headers=ro,
    )
    assert hidden.status_code == 200, hidden.text
    assert hidden.json()["data"]["products"] == []
    preview_hidden = client.get(
        "/api/v1/briefings/preview",
        params={"project_id": str(project.id), "area_id": str(area.id), "scene_code": "flood"},
        headers=ro,
    )
    assert preview_hidden.json()["data"]["empty"] is True

    assert client.post(f"/api/v1/products/{product_id}/publish", json={}, headers=duty).status_code == 200

    mapped = client.get(
        "/api/v1/products/map",
        params={"area_id": str(area.id), "project_id": str(project.id), "scene_code": "flood"},
        headers=ro,
    )
    assert mapped.status_code == 200, mapped.text
    shown = mapped.json()["data"]["products"][0]
    assert shown["id"] == product_id
    assert shown["status"] == "published"
    assert shown["flood_event_status"] == "computed"
    assert shown["baseline_version"] == "v1"
    assert shown["baseline_version_id"] == version_id
    assert shown["flood_event_ha"] == FLOOD_EVENT_HA
    assert shown["water_current_ha"] == WATER_CURRENT_HA
    by_kind = {layer["kind"]: layer for layer in shown["layers"]}
    assert by_kind["event"]["title"] == "本次淹没"
    assert by_kind["baseline"]["title"] == "本底水体"
    assert "提取水体" not in by_kind["event"]["title"]
    assert shown["impact"]["affected_road_count"] == 1
    assert shown["impact"]["affected_road_length_m"] == ROAD_M
    assert shown["impact"]["affected_settlement_count"] == 1
    assert shown["impact"]["affected_settlement_area_ha"] == SETTLEMENT_HA
    assert shown["impact"]["affected_admin_count"] == 2
    assert shown["impact"]["affected_admin_area_ha"] == ADMIN_HA

    stats = client.get(f"/api/v1/products/{product_id}/stats", headers=ro)
    assert stats.status_code == 200, stats.text
    cited = [row for row in stats.json()["data"] if row["object_type"] != "extent"]
    assert cited
    assert all(row["extra_json"]["basis"] == "flood_event" for row in cited)
    assert all(row["extra_json"]["baseline_version_id"] == version_id for row in cited)

    preview = client.get(
        "/api/v1/briefings/preview",
        params={"project_id": str(project.id), "area_id": str(area.id), "scene_code": "flood"},
        headers=duty,
    )
    assert preview.status_code == 200, preview.text
    doc = preview.json()["data"]
    assert doc["empty"] is False
    assert doc["flood_event_status"] == "computed"
    assert doc["basis_label"] == "本次淹没"
    assert doc["product"]["id"] == product_id
    assert doc["product"]["baseline_version"] == "v1"
    assert doc["product"]["baseline_version_id"] == version_id
    assert doc["stats"]["inundation_label"] == "本次淹没面积"
    assert doc["stats"]["inundation_ha"] == FLOOD_EVENT_HA
    assert doc["stats"]["flood_event_ha"] == FLOOD_EVENT_HA
    assert doc["stats"]["water_current_ha"] == WATER_CURRENT_HA
    assert doc["stats"]["affected_road_length_m"] == ROAD_M
    assert "本次淹没面积 6.75" in doc["conclusion"]
    assert "提取水体" not in doc["basis_label"]
    assert "baseline_missing" not in doc["conclusion"]

    bare = client.post(
        "/api/v1/internal/products",
        headers=INTERNAL,
        json={
            "task_id": missing.json()["data"]["id"],
            "product_type": "SARAP_FLOOD_V1",
            "title": "示例区域提取水体范围（Sentinel-1）",
            "extracted_water_ha": 18.95,
            "flood_event_status": "baseline_missing",
            "s1_product_id": "S1A_IW_GRDH_1SDV_20260701T100000_NONE",
            "metadata_json": {"crs": area.analysis_crs},
            "artifacts_json": [
                {
                    "layer_key": "water_current_poly",
                    "media_type": "application/geo+json",
                    "storage_uri": "file:///extracted.geojson",
                    "metadata_json": {
                        "crs": area.analysis_crs,
                        "geojson": _collection(
                            _ring(area, 116.50, 39.70, 116.52, 39.72, class_code=5, name="提取水体")
                        ),
                    },
                }
            ],
        },
    )
    assert bare.status_code == 201, bare.text
    bare_id = bare.json()["data"]["id"]
    assert bare.json()["data"]["flood_event_status"] == "baseline_missing"
    assert bare.json()["data"]["flood_event_ha"] is None
    assert client.post(f"/api/v1/products/{bare_id}/publish", json={}, headers=duty).status_code == 200

    # The default is the latest published product. Publishing extracted water
    # afterwards would hide 本次淹没, so the demo publishes the flood product last.
    again = client.post(f"/api/v1/products/{product_id}/publish", json={}, headers=duty)
    assert again.status_code == 409
    latest = client.get(
        "/api/v1/briefings/preview",
        params={"project_id": str(project.id), "area_id": str(area.id), "scene_code": "flood"},
        headers=ro,
    )
    # The extracted-water product was published later, so it is the default.
    assert latest.json()["data"]["product"]["id"] == bare_id
    assert latest.json()["data"]["flood_event_status"] == "baseline_missing"
    assert latest.json()["data"]["basis_label"] == "提取水体（未扣本底）"
