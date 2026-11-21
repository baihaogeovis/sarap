"""Demo-area change detection: current confident water minus a cited baseline.

The window is the in-repo 800 m public-validation fixture (open water on the
west side). No Sen1Floods11 raster is read. Numbers are the mock algorithm
path on that window, placed on the demo AOI in the area analysis CRS.
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient
from pyproj import Transformer

from sarap_engine.config import Settings
from sarap_engine.constants import ClassCode
from sarap_engine.main import create_app
from sarap_engine.orchestration.store import JobStore
from sarap_engine.orchestration.worker import Worker
from sarap_engine.products.ingest import IngestClient
from sarap_engine.products.raster_io import read_raster

DEMO_AOI = "POLYGON ((116.2 39.6, 116.8 39.6, 116.8 40.1, 116.2 40.1, 116.2 39.6))"
BASELINE_ID = "55555555-5555-4555-8555-555555555555"
AREA_ID = "11111111-1111-4111-8111-111111111111"


def _app(tmp_path: Path):
    settings = Settings(
        mode="mock",
        work_dir=tmp_path / "work",
        db_url="sqlite:///:memory:",
        ingest_mode="mock",
        run_inline=True,
        worker=False,
    )
    store = JobStore(settings.db_url)
    ingest = IngestClient(settings.platform_ingest_url, mode="mock")
    worker = Worker(store, settings, ingest_client=ingest)
    app = create_app(settings, store)
    app.state.worker = worker
    app.state.service.worker = worker
    return app, ingest


def _job(*, with_baseline: bool, task_id: str) -> dict:
    body = {
        "task_id": task_id,
        "scene_id": "33333333-3333-4333-8333-333333333333",
        "scene_code": "flood",
        "area_id": AREA_ID,
        "is_pilot": True,
        "task_type": "flood_pipeline",
        "priority": "normal",
        "algo_profile_id": "s1_grd_flood_v1",
        "s1_product_id": "S1A_IW_GRDH_1SDV_20260701T100000_DEMO",
        "acquisition_start": "2026-07-01T10:00:00Z",
        "acquisition_end": "2026-07-01T10:00:25Z",
        "pilot": {
            "area_id": AREA_ID,
            "name": "示例区域",
            "is_pilot": True,
            "analysis_crs": "EPSG:4548",
            "exchange_crs": "EPSG:4490",
            "aoi_crs": "EPSG:4490",
            "aoi_wkt": DEMO_AOI,
            "grid": {"res_m": 10, "origin_x": 0, "origin_y": 0},
            "algo_profile_id": "s1_grd_flood_v1",
            "overrides": {
                "T_default": -18,
                "T_clamp": [-23, -14],
                "mmu_ha": 0.3,
                "slope_deg": 15,
                "incidence_deg": [30, 45],
                "urban_policy": "downgrade",
                "use_vh_constraint": True,
            },
            "suggested_target_minutes": 240,
            "impact_assets": {
                "admin_county": "fixture:public_validation_window",
                "admin_township": "fixture:public_validation_window",
                "road": "fixture:public_validation_window",
                "settlement": "fixture:public_validation_window",
            },
        },
    }
    if with_baseline:
        body["baseline_version_id"] = BASELINE_ID
    return body


def _rows(stats: list[dict], object_id: str, metric: str, scope: str = "default") -> list[dict]:
    return [
        row
        for row in stats
        if row["object_id"] == object_id and row["metric"] == metric and row["scope"] == scope
    ]


def test_cited_baseline_subtracts_confident_water_on_the_demo_window(tmp_path):
    app, ingest = _app(tmp_path)
    client = TestClient(app)
    resp = client.post(
        "/internal/engine/jobs",
        json=_job(with_baseline=True, task_id="22222222-2222-4222-8222-222222222222"),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "succeeded", data.get("error_message")
    assert data["execution_mode"] == "mock"
    meta = data["product"]["metadata"]
    assert meta["flood_event_status"] == "computed"
    assert meta["baseline_version_id"] == BASELINE_ID
    assert meta["crs"] == "EPSG:4548"
    assert meta["flood_event_ha"] == 6.75
    assert meta["water_current_ha"] == 17.75
    assert meta.get("extracted_water_ha") in (None, 0)
    assert meta["lowconf_ha"] == 4.75
    assert meta["suggested_target_minutes"] == 240
    assert "depth" not in json.dumps(meta).lower()

    class_layer = next(layer for layer in data["product"]["layers"] if layer["name"] == "class_map")
    arr, grid = read_raster(Path(class_layer["uri"]))
    codes = {int(value) for value in arr.reshape(-1)}
    assert ClassCode.FLOOD_EVENT in codes
    assert ClassCode.PERMANENT_OR_BASELINE_WATER in codes
    assert ClassCode.EXTRACTED_WATER not in codes
    assert grid.crs == "EPSG:4548"
    assert grid.res_m == 10

    impact = data["product"]["impact_stats"]
    cross = impact["cross_stats"]
    assert all(row["extra"]["basis"] == "flood_event" for row in cross)
    assert all(row["extra"]["baseline_version_id"] == BASELINE_ID for row in cross)
    assert _rows(cross, "rd-cross", "affected_length_m")[0]["value"] == 301
    assert _rows(cross, "rd-dry", "affected_length_m") == []
    assert _rows(cross, "st-flood", "affected_area_ha")[0]["value"] == 0.79
    assert _rows(cross, "st-dry", "affected_area_ha") == []
    assert _rows(cross, "st-urban", "affected_area_ha") == []
    assert _rows(cross, "st-urban", "affected_area_ha", "including_lowconf")[0]["value"] > 0
    assert _rows(cross, "county-west", "affected_area_ha")[0]["value"] == 6.75
    assert _rows(cross, "township-river", "affected_area_ha")[0]["value"] == 3.15
    assert _rows(cross, "county-east", "affected_area_ha") == []
    assert _rows(cross, "township-dry", "affected_area_ha") == []
    assert _rows(cross, "rd-cross", "affected_length_m", "including_lowconf")[0]["value"] == 603

    flood = next(layer for layer in data["product"]["layers"] if layer["name"] == "flood_event_poly")
    assert not flood.get("empty")
    features = json.loads(Path(flood["uri"]).read_text(encoding="utf-8"))["features"]
    ring = features[0]["geometry"]["coordinates"][0]
    assert features[0]["properties"]["class_code"] == 3
    assert max(abs(value) for point in ring for value in point) > 1000
    to_lonlat = Transformer.from_crs("EPSG:4548", "EPSG:4326", always_xy=True)
    lons, lats = zip(*(to_lonlat.transform(x, y) for x, y in ring), strict=True)
    # Centered on the demo AOI, not parked on the projected bbox corner.
    assert 116.3 <= min(lons) and max(lons) <= 116.7
    assert 39.7 <= min(lats) and max(lats) <= 40.0

    body = next(call["body"] for call in ingest.calls if str(call["url"]).endswith("/products"))
    assert body["flood_event_status"] == "computed"
    assert body["flood_event_ha"] == 6.75
    assert body["water_current_ha"] == 17.75
    assert body["baseline_version_id"] == BASELINE_ID
    assert "flood_event_ha" in body
    keys = {item["layer_key"] for item in body["artifacts_json"]}
    assert "flood_event_poly" in keys
    assert "water_current_poly" in keys
    embedded = next(item for item in body["artifacts_json"] if item["layer_key"] == "flood_event_poly")
    assert embedded["metadata_json"]["geojson"]["features"]
    assert embedded["metadata_json"]["crs"] == "EPSG:4548"
    emergency = next(item for item in body["artifacts_json"] if item["layer_key"] == "emergency_map")
    assert emergency["metadata_json"]["document"]["basis_label"] == "本次淹没"
    assert emergency["metadata_json"]["document"]["inundation_ha"] == 6.75


def test_demo_window_without_baseline_stays_extracted_water(tmp_path):
    app, ingest = _app(tmp_path)
    client = TestClient(app)
    resp = client.post(
        "/internal/engine/jobs",
        json=_job(with_baseline=False, task_id="22222222-2222-4222-8222-222222222223"),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "succeeded", data.get("error_message")
    meta = data["product"]["metadata"]
    assert meta["flood_event_status"] == "baseline_missing"
    assert meta["extracted_water_ha"] == 18.95
    assert meta["flood_event_ha"] is None
    assert meta["extracted_water_area_label"] == "提取水体面积（未扣本底）"
    cross = data["product"]["impact_stats"]["cross_stats"]
    assert all(row["extra"]["basis"] == "extracted_water" for row in cross)
    assert _rows(cross, "rd-cross", "affected_length_m")[0]["value"] == 451
    assert _rows(cross, "st-flood", "affected_area_ha")[0]["value"] == 1.28
    assert _rows(cross, "county-west", "affected_area_ha")[0]["value"] == 18.95
    assert _rows(cross, "township-river", "affected_area_ha")[0]["value"] == 8.25
    body = next(call["body"] for call in ingest.calls if str(call["url"]).endswith("/products"))
    assert body["flood_event_status"] == "baseline_missing"
    assert "flood_event_ha" not in body
    keys = {item["layer_key"] for item in body["artifacts_json"]}
    assert "flood_event" not in keys
    assert "flood_event_poly" not in keys
