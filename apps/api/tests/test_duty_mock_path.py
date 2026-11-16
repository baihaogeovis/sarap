"""Duty-officer dispatch shape and the product a mock ingest makes visible."""

from __future__ import annotations

from tests.conftest import admin_headers, demo_ids, duty_headers

INTERNAL = {"X-Internal-Token": "test-internal-token"}


def test_dispatch_uses_area_crs_and_aoi(client, db, engine_client):
    admin = admin_headers(client)
    duty = duty_headers(client)
    _, project, area = demo_ids(db)
    updated = client.patch(
        f"/api/v1/areas/{area.id}",
        headers=admin,
        json={
            "code": area.code,
            "name": "可配置区域",
            "is_pilot": True,
            "analysis_crs": "EPSG:32650",
            "exchange_crs": "EPSG:4490",
            "grid_res_m": 10,
            "grid_origin_x": 500000,
            "grid_origin_y": 4400000,
            "aoi_geojson": area.aoi_geojson,
            "config_json": area.config_json,
        },
    )
    assert updated.status_code == 200, updated.text
    task = client.post(
        "/api/v1/tasks",
        headers=duty,
        json={
            "project_id": str(project.id),
            "area_id": str(area.id),
            "scene_code": "flood",
            "task_type": "flood_pipeline",
            "title": "按区域坐标系下发",
            "s1_product_id": "S1A_IW_GRDH_1SDV_20260701T100000_CRS",
            "acquisition_start": "2026-07-01T10:00:00Z",
        },
    )
    assert task.status_code == 201, task.text
    payload = next(iter(engine_client.jobs.values()))["payload"]
    pilot = payload["pilot"]
    assert pilot["analysis_crs"] == "EPSG:32650"
    assert pilot["grid"]["origin_x"] == 500000
    assert pilot["grid"]["origin_y"] == 4400000
    assert pilot["name"] == "可配置区域"
    assert pilot["aoi_wkt"].startswith("POLYGON")
    assert "pilot_id" not in payload
    assert payload["params"]["analysis_crs"] == "EPSG:32650"
    blob = str(payload)
    assert "长江" not in blob
    assert "淮河" not in blob


def test_dispatch_sends_staged_uri_and_published_baseline_raster(client, db, engine_client):
    admin = admin_headers(client)
    duty = duty_headers(client)
    _, project, area = demo_ids(db)
    dataset = client.post(
        "/api/v1/datasets",
        headers=admin,
        json={
            "code": "staged-mock-1",
            "name": "已入仓景",
            "dataset_type": "raster",
            "project_id": str(project.id),
            "source": "mock",
            "crs": "EPSG:4490",
            "storage_uri": "file:///data/staged/scene.safe",
            "s1_product_id": "S1A_IW_GRDH_1SDV_20260701T100000_STAGED",
            "time_start": "2026-07-01T10:00:00Z",
            "time_end": "2026-07-01T10:00:25Z",
        },
    )
    assert dataset.status_code == 201, dataset.text
    asset = client.post(
        "/api/v1/data-assets",
        headers=admin,
        json={
            "asset_code": "PERM_STAGED",
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
            "version_no": "v1",
            "crs": area.analysis_crs,
            "storage_uri": "file:///data/baselines/permanent.tif",
            "applicable_area_name": area.name,
            "source": "staged",
        },
    )
    assert version.status_code == 201, version.text
    version_id = version.json()["data"]["id"]
    published = client.post(f"/api/v1/data-asset-versions/{version_id}/publish", headers=admin, json={})
    assert published.status_code == 200, published.text
    task = client.post(
        "/api/v1/tasks",
        headers=duty,
        json={
            "project_id": str(project.id),
            "area_id": str(area.id),
            "scene_code": "flood",
            "task_type": "flood_pipeline",
            "title": "选用已入仓影像和本底",
            "imagery_dataset_id": dataset.json()["data"]["id"],
            "baseline_version_id": version_id,
        },
    )
    assert task.status_code == 201, task.text
    payload = next(iter(engine_client.jobs.values()))["payload"]
    assert payload["scene"]["input_uri"] == "file:///data/staged/scene.safe"
    assert payload["s1_product_id"].startswith("S1A_IW_GRDH")
    assert payload["baseline_version_id"] == version_id
    assert payload["baseline_uri"] == "file:///data/baselines/permanent.tif"
    assert payload["params"]["imagery_dataset_id"] == dataset.json()["data"]["id"]


def test_duty_sees_ingested_product_on_task_and_product_lists(client, db):
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
            "title": "mock 回传可见",
            "s1_product_id": "S1A_IW_GRDH_1SDV_20260701T100000_VISIBLE",
            "acquisition_start": "2026-07-01T10:00:00Z",
        },
    )
    assert created.status_code == 201, created.text
    task_id = created.json()["data"]["id"]
    ingest = client.post(
        "/api/v1/internal/products",
        headers=INTERNAL,
        json={
            "task_id": task_id,
            "product_type": "SARAP_FLOOD_V1",
            "title": "mock 洪水产品",
            "extracted_water_ha": 4.2,
            "s1_product_id": "S1A_IW_GRDH_1SDV_20260701T100000_VISIBLE",
            "artifacts_json": [{"layer_key": "class_map", "storage_uri": "file:///data/engine-work/class_map.npy"}],
            "metadata_json": {"mock": True, "crs": area.analysis_crs},
        },
    )
    assert ingest.status_code == 201, ingest.text
    product = ingest.json()["data"]
    assert product["status"] == "draft"
    assert product["task_id"] == task_id

    by_task = client.get(f"/api/v1/products?project_id={project.id}&task_id={task_id}", headers=duty)
    assert by_task.status_code == 200, by_task.text
    assert [row["id"] for row in by_task.json()["data"]] == [product["id"]]

    qc = client.get(f"/api/v1/products?project_id={project.id}", headers=duty)
    assert any(row["id"] == product["id"] and row["status"] == "draft" for row in qc.json()["data"])

    detail = client.get(f"/api/v1/tasks/{task_id}", headers=duty)
    assert detail.json()["data"]["status"] == "succeeded"
    listed = client.get(f"/api/v1/tasks?project_id={project.id}", headers=duty)
    match = next(row for row in listed.json()["data"] if row["id"] == task_id)
    assert match["status"] == "succeeded"
    assert match["progress"] == 100
