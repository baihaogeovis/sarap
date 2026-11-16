from __future__ import annotations

from datetime import datetime, timezone

from tests.conftest import admin_headers, demo_ids, duty_headers


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def test_legacy_baselines_do_not_count_as_flood_baseline(client, db):
    """Old /baselines rows must not unlock flood_event layers."""
    duty = duty_headers(client)
    admin = admin_headers(client)
    _, project, area = demo_ids(db)
    dataset = client.post(
        "/api/v1/datasets",
        headers=admin,
        json={"code": "legacy-ds", "name": "旧编目", "dataset_type": "raster", "project_id": str(project.id)},
    )
    assert dataset.status_code == 201, dataset.text
    baseline = client.post(
        "/api/v1/baselines",
        headers=admin,
        json={
            "code": "BASE_PERM_WATER_LEGACY",
            "name": "旧本底",
            "category": "permanent_water",
            "version": "v-legacy",
            "dataset_id": dataset.json()["data"]["id"],
            "project_id": str(project.id),
            "applicable_area_name": area.name,
        },
    )
    assert baseline.status_code == 201, baseline.text
    reviewed = client.post(
        f"/api/v1/baselines/{baseline.json()['data']['id']}/review",
        headers=admin,
        json={"review_status": "published", "comment": "旧接口发布"},
    )
    assert reviewed.status_code == 200

    product = client.post(
        "/api/v1/products",
        headers=duty,
        json={
            "project_id": str(project.id),
            "area_id": str(area.id),
            "scene_code": "flood",
            "product_type": "SARAP_FLOOD_V1",
            "title": "仅有旧本底",
            "baseline_asset_id": baseline.json()["data"]["id"],
            "baseline_version": "v-legacy",
            "extracted_water_ha": 3.141,
            "flood_event_ha": 9.99,
            "artifacts_json": [
                {"layer_key": "class_map", "storage_uri": "file://cm.tif"},
                {"layer_key": "flood_event", "storage_uri": "file://should_omit.tif"},
            ],
        },
    )
    assert product.status_code == 201, product.text
    body = product.json()["data"]
    assert body["flood_event_status"] == "baseline_missing"
    assert body["baseline_version_id"] is None
    assert body["extracted_water_ha"] == 3.14
    assert body["flood_event_ha"] is None
    layers = client.get(f"/api/v1/products/{body['id']}/layers", headers=duty)
    assert "flood_event" not in layers.json()["meta"]["layer_keys"]
    assert "flood_event" not in {row["layer_key"] for row in layers.json()["data"]}
    stats = client.get(f"/api/v1/products/{body['id']}/stats", headers=duty)
    metrics = {row["metric"]: row for row in stats.json()["meta"]["area_metrics"]}
    assert metrics["extracted_water_ha"]["label"] == "提取水体面积（未扣本底）"
    assert metrics["extracted_water_ha"]["value"] == 3.14
    assert metrics["extracted_water_m2"]["value"] == 31400
    assert metrics["extracted_water_m2"]["unit"] == "m2"


def _box(minx, miny, maxx, maxy):
    return {
        "type": "Polygon",
        "coordinates": [[[minx, miny], [maxx, miny], [maxx, maxy], [minx, maxy], [minx, miny]]],
    }


# Demo area AOI is 116.2–116.8E, 39.6–40.1N (seed).
DEMO_COVERING = _box(116.0, 39.0, 117.5, 41.0)
DEMO_OUTSIDE = _box(120.5, 31.0, 121.5, 32.0)


def _publish_water_version(
    client,
    admin,
    project_id,
    area,
    asset_id,
    version_no,
    valid_from,
    valid_to=None,
    *,
    applicable_area_name=None,
    applicable_area_geojson=None,
    include_name=True,
):
    payload = {
        "version_no": version_no,
        "valid_from": _iso(valid_from) if valid_from else None,
        "valid_to": _iso(valid_to) if valid_to else None,
        "storage_uri": f"file://{version_no}.tif",
    }
    if include_name:
        payload["applicable_area_name"] = area.name if applicable_area_name is None else applicable_area_name
    elif applicable_area_name is not None:
        payload["applicable_area_name"] = applicable_area_name
    if applicable_area_geojson is not None:
        payload["applicable_area_geojson"] = applicable_area_geojson
    created = client.post(
        f"/api/v1/data-assets/{asset_id}/versions",
        headers=admin,
        json=payload,
    )
    assert created.status_code == 201, created.text
    vid = created.json()["data"]["id"]
    pub = client.post(f"/api/v1/data-asset-versions/{vid}/publish", headers=admin, json={"comment": "发布"})
    assert pub.status_code == 200, pub.text
    return vid


def test_baseline_version_conflict_requires_preferred_id(client, db):
    admin = admin_headers(client)
    duty = duty_headers(client)
    _, project, area = demo_ids(db)
    asset = client.post(
        "/api/v1/data-assets",
        headers=admin,
        json={
            "asset_code": "BASE_PERM_WATER_DEMO",
            "name": "常年水体",
            "asset_type": "permanent_water",
            "project_id": str(project.id),
            "area_id": str(area.id),
        },
    )
    assert asset.status_code == 201, asset.text
    asset_id = asset.json()["data"]["id"]
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    v1 = _publish_water_version(client, admin, project.id, area, asset_id, "v2026.01", t0)
    v2 = _publish_water_version(client, admin, project.id, area, asset_id, "v2026.06", t0)
    acq = datetime(2026, 7, 1, 11, 22, 33, tzinfo=timezone.utc)

    conflict = client.post(
        "/api/v1/tasks",
        headers=duty,
        json={
            "project_id": str(project.id),
            "area_id": str(area.id),
            "scene_code": "flood",
            "task_type": "water_extract",
            "title": "冲突应失败",
            "acquisition_start": _iso(acq),
            "s1_product_id": "S1A_IW_GRDH_1SDV_20260701T112233_XXXX",
        },
    )
    assert conflict.status_code == 409, conflict.text
    assert conflict.json()["error"]["code"] == "BASELINE_VERSION_CONFLICT"

    # invalid preferred still fails
    bad = dict(area.config_json or {})
    bad.setdefault("baselines", {})["preferred_version_id"] = "00000000-0000-0000-0000-000000000099"
    bad["baselines"]["permanent_water_asset_id"] = asset_id
    patched = client.patch(
        f"/api/v1/areas/{area.id}",
        headers=admin,
        json={
            "code": area.code,
            "name": area.name,
            "is_pilot": area.is_pilot,
            "timezone": area.timezone,
            "aoi_geojson": area.aoi_geojson,
            "bbox_json": area.bbox_json,
            "analysis_crs": area.analysis_crs,
            "exchange_crs": area.exchange_crs,
            "grid_res_m": area.grid_res_m,
            "grid_origin_x": area.grid_origin_x,
            "grid_origin_y": area.grid_origin_y,
            "config_json": bad,
        },
    )
    assert patched.status_code == 200, patched.text
    still = client.post(
        "/api/v1/tasks",
        headers=duty,
        json={
            "project_id": str(project.id),
            "area_id": str(area.id),
            "scene_code": "flood",
            "task_type": "water_extract",
            "title": "无效 preferred",
            "acquisition_start": _iso(acq),
            "s1_product_id": "S1A_IW_GRDH_1SDV_20260701T112233_YYYY",
        },
    )
    assert still.status_code == 409
    # Non-existent preferred id is a more specific published-status error, not a silent pick.
    assert still.json()["error"]["code"] == "BASELINE_NOT_PUBLISHED"

    good = dict(patched.json()["data"]["config_json"])
    good["baselines"]["preferred_version_id"] = v2
    client.patch(
        f"/api/v1/areas/{area.id}",
        headers=admin,
        json={
            "code": area.code,
            "name": area.name,
            "is_pilot": area.is_pilot,
            "timezone": area.timezone,
            "aoi_geojson": area.aoi_geojson,
            "bbox_json": area.bbox_json,
            "analysis_crs": area.analysis_crs,
            "exchange_crs": area.exchange_crs,
            "grid_res_m": area.grid_res_m,
            "grid_origin_x": area.grid_origin_x,
            "grid_origin_y": area.grid_origin_y,
            "config_json": good,
        },
    )
    ok = client.post(
        "/api/v1/tasks",
        headers=duty,
        json={
            "project_id": str(project.id),
            "area_id": str(area.id),
            "scene_code": "flood",
            "task_type": "water_extract",
            "title": "已指定 preferred",
            "acquisition_start": _iso(acq),
            "s1_product_id": "S1A_IW_GRDH_1SDV_20260701T112233_ZZZZ",
        },
    )
    assert ok.status_code == 201, ok.text
    assert ok.json()["data"]["baseline_version_id"] == v2
    # referenced version cannot be soft-deleted
    blocked = client.delete(f"/api/v1/data-asset-versions/{v2}", headers=admin)
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "BASELINE_IN_USE"
    dep = client.post(f"/api/v1/data-asset-versions/{v1}/deprecate", headers=admin, json={"comment": "旧版"})
    assert dep.status_code == 200
    assert dep.json()["data"]["review_status"] == "deprecated"
    # v1 is unused so leftover of conflict pair; deprecate is the supported path


def test_product_and_task_expose_acquisition_and_s1_id(client, db):
    admin = admin_headers(client)
    duty = duty_headers(client)
    _, project, area = demo_ids(db)
    start = datetime(2026, 6, 1, 11, 22, 33, tzinfo=timezone.utc)
    end = datetime(2026, 6, 1, 11, 23, 0, tzinfo=timezone.utc)
    s1_id = "S1A_IW_GRDH_1SDV_20260601T112233_20260601T112300_000000_000000_0000"
    dataset = client.post(
        "/api/v1/datasets",
        headers=admin,
        json={
            "code": s1_id,
            "name": "S1 景",
            "dataset_type": "raster",
            "project_id": str(project.id),
            "time_start": _iso(start),
            "time_end": _iso(end),
            "s1_product_id": s1_id,
        },
    )
    assert dataset.status_code == 201, dataset.text
    ds = dataset.json()["data"]
    assert ds["time_start"].startswith("2026-06-01T11:22:33")
    assert ds["time_end"].startswith("2026-06-01T11:23:00")
    assert ds["s1_product_id"] == s1_id

    task = client.post(
        "/api/v1/tasks",
        headers=duty,
        json={
            "project_id": str(project.id),
            "area_id": str(area.id),
            "scene_code": "flood",
            "task_type": "water_extract",
            "title": "带成像时间",
            "imagery_dataset_id": ds["id"],
            "data_ready_at": "2026-06-01T12:00:00Z",
        },
    )
    assert task.status_code == 201, task.text
    tbody = task.json()["data"]
    assert tbody["scene_code"] == "flood"
    assert tbody["s1_product_id"] == s1_id
    assert tbody["acquisition_start"].startswith("2026-06-01T11:22:33")
    assert tbody["acquisition_end"].startswith("2026-06-01T11:23:00")
    # auto idempotency: same imagery/area/params returns the same task
    again = client.post(
        "/api/v1/tasks",
        headers=duty,
        json={
            "project_id": str(project.id),
            "area_id": str(area.id),
            "scene_code": "flood",
            "task_type": "water_extract",
            "title": "带成像时间-重复",
            "imagery_dataset_id": ds["id"],
            "data_ready_at": "2026-06-01T12:00:00Z",
        },
    )
    assert again.status_code == 200
    assert again.json()["data"]["id"] == tbody["id"]

    ingested = client.post(
        "/api/v1/internal/products",
        headers={"X-Internal-Token": "test-internal-token"},
        json={
            "task_id": tbody["id"],
            "product_type": "SARAP_FLOOD_V1",
            "title": "回传产品",
            "imagery_dataset_id": ds["id"],
            "extracted_water_ha": 2.5,
        },
    )
    assert ingested.status_code == 201, ingested.text
    pbody = ingested.json()["data"]
    assert pbody["scene_code"] == "flood"
    assert pbody["s1_product_id"] == s1_id
    assert pbody["acquisition_start"].startswith("2026-06-01T11:22:33")
    assert pbody["acquisition_end"].startswith("2026-06-01T11:23:00")
    assert pbody["flood_event_status"] == "baseline_missing"
    assert pbody["s1_product_id"] != pbody["scene_code"]


def test_new_area_picks_gauss_kruger_belt_from_aoi(client, db):
    admin = admin_headers(client)
    _, project, _ = demo_ids(db)
    # ~121°E should be CM 120E → EPSG:4549, not the example 4548
    created = client.post(
        f"/api/v1/projects/{project.id}/areas",
        headers=admin,
        json={
            "code": "east-area",
            "name": "东侧示例区域",
            "is_pilot": True,
            "aoi_geojson": {
                "type": "Polygon",
                "coordinates": [[[120.5, 31.0], [121.5, 31.0], [121.5, 32.0], [120.5, 32.0], [120.5, 31.0]]],
            },
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["data"]["analysis_crs"] == "EPSG:4549"



def test_dispatch_payload_includes_scene_area_and_imagery(client, db, engine_client):
    admin = admin_headers(client)
    duty = duty_headers(client)
    org, project, area = demo_ids(db)
    assert area.is_pilot is True
    start = datetime(2026, 8, 2, 3, 4, 5, tzinfo=timezone.utc)
    end = datetime(2026, 8, 2, 3, 4, 32, tzinfo=timezone.utc)
    s1_id = "S1A_IW_GRDH_1SDV_20260802T030405_20260802T030432_000000_000000_0000"
    dataset = client.post(
        "/api/v1/datasets",
        headers=admin,
        json={
            "code": "dispatch-s1",
            "name": "调度用景",
            "dataset_type": "raster",
            "project_id": str(project.id),
            "time_start": _iso(start),
            "time_end": _iso(end),
            "s1_product_id": s1_id,
        },
    )
    assert dataset.status_code == 201, dataset.text
    task = client.post(
        "/api/v1/tasks",
        headers=duty,
        json={
            "project_id": str(project.id),
            "area_id": str(area.id),
            "scene_code": "flood",
            "task_type": "water_extract",
            "title": "调度载荷",
            "imagery_dataset_id": dataset.json()["data"]["id"],
            "algo_profile_id": "s1_grd_flood_v1",
        },
    )
    assert task.status_code == 201, task.text
    tbody = task.json()["data"]
    assert engine_client.jobs
    payload = next(iter(engine_client.jobs.values()))["payload"]
    assert payload["task_id"] == tbody["id"]
    assert payload["scene_id"] == tbody["scene_id"]
    assert payload["scene_code"] == "flood"
    assert payload["scene_id"] != payload.get("s1_product_id")
    assert payload["area_id"] == str(area.id)
    assert payload["s1_product_id"] == s1_id
    assert payload["acquisition_start"].startswith("2026-08-02T03:04:05")
    assert payload["acquisition_end"].startswith("2026-08-02T03:04:32")
    assert payload["algo_profile_id"] == "s1_grd_flood_v1"
    assert "baseline_version_id" not in payload
    assert payload["is_pilot"] is True
    assert payload["params"].get("is_pilot") is True
    assert "pilot_id" not in payload



def _create_water_asset(client, admin, project_id, asset_code, area_id=None):
    body = {
        "asset_code": asset_code,
        "name": "常年水体",
        "asset_type": "permanent_water",
        "project_id": str(project_id),
    }
    if area_id is not None:
        body["area_id"] = str(area_id)
    created = client.post("/api/v1/data-assets", headers=admin, json=body)
    assert created.status_code == 201, created.text
    return created.json()["data"]["id"]


def test_empty_name_same_org_published_is_not_auto_bound(client, db):
    """Name empty, no geometry, no matching area_id → do not auto-bind org-wide published versions."""
    admin = admin_headers(client)
    duty = duty_headers(client)
    _, project, area = demo_ids(db)
    other = client.post(
        f"/api/v1/projects/{project.id}/areas",
        headers=admin,
        json={
            "code": "other-area",
            "name": "另一区域",
            "is_pilot": False,
            "aoi_geojson": DEMO_OUTSIDE,
        },
    )
    assert other.status_code == 201, other.text
    other_id = other.json()["data"]["id"]
    asset_id = _create_water_asset(client, admin, project.id, "BASE_PERM_WATER_OTHER", area_id=other_id)
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    _publish_water_version(
        client, admin, project.id, area, asset_id, "v-loose", t0,
        include_name=False, applicable_area_name="",
    )
    acq = datetime(2026, 7, 1, 11, 0, 0, tzinfo=timezone.utc)
    task = client.post(
        "/api/v1/tasks",
        headers=duty,
        json={
            "project_id": str(project.id),
            "area_id": str(area.id),
            "scene_code": "flood",
            "task_type": "water_extract",
            "title": "不应自动绑本底",
            "acquisition_start": _iso(acq),
            "s1_product_id": "S1A_IW_GRDH_1SDV_20260701T110000_NOBIND",
        },
    )
    assert task.status_code == 201, task.text
    assert task.json()["data"]["baseline_version_id"] is None


def test_geometry_covers_and_valid_period_auto_binds(client, db):
    admin = admin_headers(client)
    duty = duty_headers(client)
    _, project, area = demo_ids(db)
    # No area_id, empty name: only geometry should make it applicable.
    asset_id = _create_water_asset(client, admin, project.id, "BASE_PERM_WATER_GEO")
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    t1 = datetime(2026, 12, 31, tzinfo=timezone.utc)
    vid = _publish_water_version(
        client, admin, project.id, area, asset_id, "v-cover", t0, t1,
        include_name=False, applicable_area_name="",
        applicable_area_geojson=DEMO_COVERING,
    )
    acq = datetime(2026, 7, 1, 11, 0, 0, tzinfo=timezone.utc)
    task = client.post(
        "/api/v1/tasks",
        headers=duty,
        json={
            "project_id": str(project.id),
            "area_id": str(area.id),
            "scene_code": "flood",
            "task_type": "water_extract",
            "title": "几何包含应绑定",
            "acquisition_start": _iso(acq),
            "s1_product_id": "S1A_IW_GRDH_1SDV_20260701T110000_COVER",
        },
    )
    assert task.status_code == 201, task.text
    assert task.json()["data"]["baseline_version_id"] == vid


def test_explicit_version_outside_validity_period_is_409(client, db):
    admin = admin_headers(client)
    duty = duty_headers(client)
    _, project, area = demo_ids(db)
    asset_id = _create_water_asset(client, admin, project.id, "BASE_PERM_WATER_PERIOD", area_id=area.id)
    vid = _publish_water_version(
        client, admin, project.id, area, asset_id, "v-expired",
        datetime(2026, 1, 1, tzinfo=timezone.utc),
        datetime(2026, 6, 1, tzinfo=timezone.utc),
    )
    acq = datetime(2026, 7, 1, 11, 0, 0, tzinfo=timezone.utc)
    task = client.post(
        "/api/v1/tasks",
        headers=duty,
        json={
            "project_id": str(project.id),
            "area_id": str(area.id),
            "scene_code": "flood",
            "task_type": "water_extract",
            "title": "时段不满足",
            "acquisition_start": _iso(acq),
            "s1_product_id": "S1A_IW_GRDH_1SDV_20260701T110000_EXPIRED",
            "baseline_version_id": vid,
        },
    )
    assert task.status_code == 409, task.text
    assert task.json()["error"]["code"] == "BASELINE_NOT_IN_VALIDITY_PERIOD"


def test_explicit_version_geometry_not_covering_is_409(client, db):
    admin = admin_headers(client)
    duty = duty_headers(client)
    _, project, area = demo_ids(db)
    asset_id = _create_water_asset(client, admin, project.id, "BASE_PERM_WATER_OUT")
    vid = _publish_water_version(
        client, admin, project.id, area, asset_id, "v-outside",
        datetime(2026, 1, 1, tzinfo=timezone.utc),
        include_name=False, applicable_area_name="",
        applicable_area_geojson=DEMO_OUTSIDE,
    )
    acq = datetime(2026, 7, 1, 11, 0, 0, tzinfo=timezone.utc)
    task = client.post(
        "/api/v1/tasks",
        headers=duty,
        json={
            "project_id": str(project.id),
            "area_id": str(area.id),
            "scene_code": "flood",
            "task_type": "water_extract",
            "title": "几何不包含",
            "acquisition_start": _iso(acq),
            "s1_product_id": "S1A_IW_GRDH_1SDV_20260701T110000_OUT",
            "baseline_version_id": vid,
        },
    )
    assert task.status_code == 409, task.text
    assert task.json()["error"]["code"] == "BASELINE_AREA_NOT_APPLICABLE"



def _with_crs(geom: dict, crs: str) -> dict:
    return {**geom, "crs": {"type": "name", "properties": {"name": crs}}}


def _create_area(client, admin, project_id, code, name, *, aoi_geojson=None, exchange_crs="EPSG:4490"):
    body = {
        "code": code,
        "name": name,
        "is_pilot": False,
        "exchange_crs": exchange_crs,
    }
    if aoi_geojson is not None:
        body["aoi_geojson"] = aoi_geojson
    created = client.post(f"/api/v1/projects/{project_id}/areas", headers=admin, json=body)
    assert created.status_code == 201, created.text
    return created.json()["data"]


def test_crs_mismatch_between_lonlat_and_gauss_kruger_is_409(client, db):
    """Lon/lat (4490/4326) vs Gauss-Kruger metres must not be covers-compared."""
    admin = admin_headers(client)
    duty = duty_headers(client)
    _, project, area = demo_ids(db)
    # Approximate EPSG:4548 (CM 117E) metres around the demo AOI — must not be
    # silently compared against the area's unmarked lon/lat AOI (exchange_crs 4490).
    gk = _with_crs(_box(400000, 4300000, 500000, 4500000), "EPSG:4548")
    asset_id = _create_water_asset(client, admin, project.id, "BASE_PERM_WATER_GK")
    vid = _publish_water_version(
        client, admin, project.id, area, asset_id, "v-gk",
        datetime(2026, 1, 1, tzinfo=timezone.utc),
        include_name=False, applicable_area_name="",
        applicable_area_geojson=gk,
    )
    acq = datetime(2026, 7, 1, 11, 0, 0, tzinfo=timezone.utc)
    explicit = client.post(
        "/api/v1/tasks",
        headers=duty,
        json={
            "project_id": str(project.id),
            "area_id": str(area.id),
            "scene_code": "flood",
            "task_type": "water_extract",
            "title": "CRS 不一致显式",
            "acquisition_start": _iso(acq),
            "s1_product_id": "S1A_IW_GRDH_1SDV_20260701T110000_CRSX",
            "baseline_version_id": vid,
        },
    )
    assert explicit.status_code == 409, explicit.text
    assert explicit.json()["error"]["code"] == "BASELINE_CRS_MISMATCH"

    auto = client.post(
        "/api/v1/tasks",
        headers=duty,
        json={
            "project_id": str(project.id),
            "area_id": str(area.id),
            "scene_code": "flood",
            "task_type": "water_extract",
            "title": "CRS 不一致自动",
            "acquisition_start": _iso(acq),
            "s1_product_id": "S1A_IW_GRDH_1SDV_20260701T110000_CRSA",
        },
    )
    assert auto.status_code == 409, auto.text
    assert auto.json()["error"]["code"] == "BASELINE_CRS_MISMATCH"


def test_unmarked_lonlat_geojson_uses_exchange_crs_and_binds(client, db):
    admin = admin_headers(client)
    duty = duty_headers(client)
    _, project, area = demo_ids(db)
    assert (area.exchange_crs or "EPSG:4490") == "EPSG:4490"
    asset_id = _create_water_asset(client, admin, project.id, "BASE_PERM_WATER_LL")
    vid = _publish_water_version(
        client, admin, project.id, area, asset_id, "v-ll",
        datetime(2026, 1, 1, tzinfo=timezone.utc),
        include_name=False, applicable_area_name="",
        applicable_area_geojson=DEMO_COVERING,  # unmarked lon/lat
    )
    acq = datetime(2026, 7, 1, 11, 0, 0, tzinfo=timezone.utc)
    task = client.post(
        "/api/v1/tasks",
        headers=duty,
        json={
            "project_id": str(project.id),
            "area_id": str(area.id),
            "scene_code": "flood",
            "task_type": "water_extract",
            "title": "未标明 crs 的经纬度可绑定",
            "acquisition_start": _iso(acq),
            "s1_product_id": "S1A_IW_GRDH_1SDV_20260701T110000_LL",
        },
    )
    assert task.status_code == 201, task.text
    assert task.json()["data"]["baseline_version_id"] == vid


def test_missing_aoi_falls_back_to_matching_area_id(client, db):
    admin = admin_headers(client)
    duty = duty_headers(client)
    _, project, _ = demo_ids(db)
    bare = _create_area(client, admin, project.id, "no-aoi-match", "无 AOI 可回退")
    assert not bare.get("aoi_geojson")
    asset_id = _create_water_asset(client, admin, project.id, "BASE_PERM_WATER_NOAOI", area_id=bare["id"])
    vid = _publish_water_version(
        client, admin, project.id, bare, asset_id, "v-noaoi",
        datetime(2026, 1, 1, tzinfo=timezone.utc),
        include_name=False, applicable_area_name="",
        applicable_area_geojson=DEMO_COVERING,
    )
    acq = datetime(2026, 7, 1, 11, 0, 0, tzinfo=timezone.utc)
    task = client.post(
        "/api/v1/tasks",
        headers=duty,
        json={
            "project_id": str(project.id),
            "area_id": bare["id"],
            "scene_code": "flood",
            "task_type": "water_extract",
            "title": "无 AOI 回退 area_id",
            "acquisition_start": _iso(acq),
            "s1_product_id": "S1A_IW_GRDH_1SDV_20260701T110000_NOAOI",
        },
    )
    assert task.status_code == 201, task.text
    assert task.json()["data"]["baseline_version_id"] == vid


def test_missing_aoi_without_area_id_match_is_not_applicable(client, db):
    admin = admin_headers(client)
    duty = duty_headers(client)
    _, project, area = demo_ids(db)
    bare = _create_area(client, admin, project.id, "no-aoi-other", "无 AOI 无匹配")
    # Asset is attached to the seeded demo area, not the bare area.
    asset_id = _create_water_asset(client, admin, project.id, "BASE_PERM_WATER_NOAOI2", area_id=area.id)
    vid = _publish_water_version(
        client, admin, project.id, area, asset_id, "v-noaoi2",
        datetime(2026, 1, 1, tzinfo=timezone.utc),
        include_name=False, applicable_area_name="",
        applicable_area_geojson=DEMO_COVERING,
    )
    acq = datetime(2026, 7, 1, 11, 0, 0, tzinfo=timezone.utc)
    explicit = client.post(
        "/api/v1/tasks",
        headers=duty,
        json={
            "project_id": str(project.id),
            "area_id": bare["id"],
            "scene_code": "flood",
            "task_type": "water_extract",
            "title": "无 AOI 且 area_id 不匹配",
            "acquisition_start": _iso(acq),
            "s1_product_id": "S1A_IW_GRDH_1SDV_20260701T110000_NOAOIX",
            "baseline_version_id": vid,
        },
    )
    assert explicit.status_code == 409, explicit.text
    assert explicit.json()["error"]["code"] == "BASELINE_AREA_NOT_APPLICABLE"

    auto = client.post(
        "/api/v1/tasks",
        headers=duty,
        json={
            "project_id": str(project.id),
            "area_id": bare["id"],
            "scene_code": "flood",
            "task_type": "water_extract",
            "title": "无 AOI 自动不绑定",
            "acquisition_start": _iso(acq),
            "s1_product_id": "S1A_IW_GRDH_1SDV_20260701T110000_NOAOIA",
        },
    )
    assert auto.status_code == 201, auto.text
    assert auto.json()["data"]["baseline_version_id"] is None



def _patch_preferred(client, admin, area, preferred_version_id, asset_id=None):
    cfg = dict(area.config_json or {})
    if hasattr(area, "config_json") and not isinstance(area, dict):
        cfg = dict(area.config_json or {})
        code, name = area.code, area.name
        is_pilot, tz = area.is_pilot, area.timezone
        aoi, bbox = area.aoi_geojson, area.bbox_json
        analysis, exchange = area.analysis_crs, area.exchange_crs
        grid_res, ox, oy = area.grid_res_m, area.grid_origin_x, area.grid_origin_y
        area_id = area.id
    else:
        cfg = dict(area.get("config_json") or {})
        code, name = area["code"], area["name"]
        is_pilot, tz = area["is_pilot"], area["timezone"]
        aoi, bbox = area.get("aoi_geojson"), area.get("bbox_json")
        analysis, exchange = area.get("analysis_crs"), area.get("exchange_crs")
        grid_res, ox, oy = area.get("grid_res_m"), area.get("grid_origin_x"), area.get("grid_origin_y")
        area_id = area["id"]
    cfg.setdefault("baselines", {})
    cfg["baselines"]["preferred_version_id"] = preferred_version_id
    if asset_id is not None:
        cfg["baselines"]["permanent_water_asset_id"] = asset_id
    patched = client.patch(
        f"/api/v1/areas/{area_id}",
        headers=admin,
        json={
            "code": code,
            "name": name,
            "is_pilot": is_pilot,
            "timezone": tz,
            "aoi_geojson": aoi,
            "bbox_json": bbox,
            "analysis_crs": analysis,
            "exchange_crs": exchange,
            "grid_res_m": grid_res,
            "grid_origin_x": ox,
            "grid_origin_y": oy,
            "config_json": cfg,
        },
    )
    assert patched.status_code == 200, patched.text
    return patched.json()["data"]


def test_auto_resolve_skips_crs_mismatch_and_binds_valid_version(client, db):
    """A bad-CRS published version must not block a valid one during auto-resolve."""
    admin = admin_headers(client)
    duty = duty_headers(client)
    _, project, area = demo_ids(db)
    asset_id = _create_water_asset(client, admin, project.id, "BASE_PERM_WATER_MIX")
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    gk = _with_crs(_box(400000, 4300000, 500000, 4500000), "EPSG:4548")
    _publish_water_version(
        client, admin, project.id, area, asset_id, "v-gk", t0,
        include_name=False, applicable_area_name="",
        applicable_area_geojson=gk,
    )
    good = _publish_water_version(
        client, admin, project.id, area, asset_id, "v-ll", t0,
        include_name=False, applicable_area_name="",
        applicable_area_geojson=DEMO_COVERING,
    )
    acq = datetime(2026, 7, 1, 11, 0, 0, tzinfo=timezone.utc)
    task = client.post(
        "/api/v1/tasks",
        headers=duty,
        json={
            "project_id": str(project.id),
            "area_id": str(area.id),
            "scene_code": "flood",
            "task_type": "water_extract",
            "title": "跳过错误 CRS 绑定可用版本",
            "acquisition_start": _iso(acq),
            "s1_product_id": "S1A_IW_GRDH_1SDV_20260701T110000_MIX",
        },
    )
    assert task.status_code == 201, task.text
    assert task.json()["data"]["baseline_version_id"] == good


def test_preferred_crs_mismatch_is_409_even_if_another_version_is_valid(client, db):
    admin = admin_headers(client)
    duty = duty_headers(client)
    _, project, area = demo_ids(db)
    asset_id = _create_water_asset(client, admin, project.id, "BASE_PERM_WATER_PREFCRS", area_id=area.id)
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    gk = _with_crs(_box(400000, 4300000, 500000, 4500000), "EPSG:4548")
    bad = _publish_water_version(
        client, admin, project.id, area, asset_id, "v-gk-pref", t0,
        include_name=False, applicable_area_name="",
        applicable_area_geojson=gk,
    )
    _publish_water_version(
        client, admin, project.id, area, asset_id, "v-ll-pref", t0,
        include_name=False, applicable_area_name="",
        applicable_area_geojson=DEMO_COVERING,
    )
    _patch_preferred(client, admin, area, bad, asset_id=asset_id)
    acq = datetime(2026, 7, 1, 11, 0, 0, tzinfo=timezone.utc)
    task = client.post(
        "/api/v1/tasks",
        headers=duty,
        json={
            "project_id": str(project.id),
            "area_id": str(area.id),
            "scene_code": "flood",
            "task_type": "water_extract",
            "title": "preferred 指向错误 CRS",
            "acquisition_start": _iso(acq),
            "s1_product_id": "S1A_IW_GRDH_1SDV_20260701T110000_PREFCRS",
        },
    )
    assert task.status_code == 409, task.text
    assert task.json()["error"]["code"] == "BASELINE_CRS_MISMATCH"


def test_unrelated_crs_mismatch_does_not_block_p0_no_baseline(client, db):
    """A messy-CRS version that is not otherwise applicable must not raise CRS mismatch."""
    admin = admin_headers(client)
    duty = duty_headers(client)
    _, project, area = demo_ids(db)
    other = _create_area(
        client, admin, project.id, "other-crs-area", "另一区域",
        aoi_geojson=DEMO_OUTSIDE,
    )
    asset_id = _create_water_asset(
        client, admin, project.id, "BASE_PERM_WATER_UNREL", area_id=other["id"]
    )
    gk = _with_crs(_box(400000, 4300000, 500000, 4500000), "EPSG:4548")
    _publish_water_version(
        client, admin, project.id, area,
        asset_id, "v-unrel",
        datetime(2026, 1, 1, tzinfo=timezone.utc),
        include_name=True, applicable_area_name=other["name"],
        applicable_area_geojson=gk,
    )
    acq = datetime(2026, 7, 1, 11, 0, 0, tzinfo=timezone.utc)
    task = client.post(
        "/api/v1/tasks",
        headers=duty,
        json={
            "project_id": str(project.id),
            "area_id": str(area.id),
            "scene_code": "flood",
            "task_type": "water_extract",
            "title": "无关 CRS 错误不误报",
            "acquisition_start": _iso(acq),
            "s1_product_id": "S1A_IW_GRDH_1SDV_20260701T110000_UNREL",
        },
    )
    assert task.status_code == 201, task.text
    assert task.json()["data"]["baseline_version_id"] is None
