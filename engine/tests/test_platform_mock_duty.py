"""Platform-shaped jobs: area CRS, mock worker, and no silent snap→mock fallback."""

from __future__ import annotations

import time

from fastapi.testclient import TestClient

from sarap_engine.config import Settings
from sarap_engine.main import create_app
from sarap_engine.orchestration.loop import start_background_worker
from sarap_engine.orchestration.store import JobStore
from sarap_engine.orchestration.worker import Worker
from sarap_engine.products.ingest import IngestClient


def _settings(tmp_path, **overrides) -> Settings:
    data = dict(
        mode="mock",
        work_dir=tmp_path / "work",
        db_url="sqlite:///:memory:",
        ingest_mode="mock",
        run_inline=True,
        worker=False,
    )
    data.update(overrides)
    return Settings(**data)


def _app(settings: Settings):
    store = JobStore(settings.db_url)
    ingest = IngestClient(settings.platform_ingest_url, mode=settings.ingest_mode)
    worker = Worker(store, settings, ingest_client=ingest)
    app = create_app(settings, store)
    app.state.worker = worker
    app.state.service.worker = worker
    return app


def _platform_job(**extra):
    area_id = "11111111-1111-4111-8111-111111111111"
    body = {
        "task_id": "22222222-2222-4222-8222-222222222222",
        "scene_id": "33333333-3333-4333-8333-333333333333",
        "scene_code": "flood",
        "area_id": area_id,
        "is_pilot": True,
        "task_type": "flood_pipeline",
        "priority": "normal",
        "algo_profile_id": "s1_grd_flood_v1",
        "pilot": {
            "area_id": area_id,
            "name": "可配置区域",
            "is_pilot": True,
            "analysis_crs": "EPSG:32650",
            "exchange_crs": "EPSG:4490",
            "aoi_crs": "EPSG:4490",
            "aoi_wkt": "POLYGON ((116.2 39.6, 116.8 39.6, 116.8 40.1, 116.2 40.1, 116.2 39.6))",
            "grid": {"res_m": 10, "origin_x": 500000, "origin_y": 4400000},
            "algo_profile_id": "s1_grd_flood_v1",
            "overrides": {
                "T_default": -18,
                "T_clamp": [-23, -14],
                "mmu_ha": 0.3,
                "slope_deg": 15,
                "incidence_deg": [30, 45],
                "urban_policy": "downgrade",
                "use_vh_constraint": True,
                "use_preevent": False,
                "buffer_km": 2,
            },
            "suggested_target_minutes": 240,
        },
        "params": {
            "analysis_crs": "EPSG:32650",
            "imagery_dataset_id": "44444444-4444-4444-8444-444444444444",
        },
    }
    body.update(extra)
    return body


def test_platform_job_mock_uses_area_crs_and_marks_mock(tmp_path):
    app = _app(_settings(tmp_path))
    client = TestClient(app)
    resp = client.post("/internal/engine/jobs", json=_platform_job())
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "succeeded"
    assert data["execution_mode"] == "mock"
    meta = data["product"]["metadata"]
    assert meta["crs"] == "EPSG:32650"
    assert meta["grid_origin"][0] == 500000
    assert meta["grid_origin"][1] == 4400000
    assert meta["extras"]["mock"] is True
    assert meta["flood_event_status"] == "baseline_missing"
    assert meta["suggested_target_minutes"] == 240
    assert "depth" not in str(meta).lower()


def test_mock_published_baseline_without_raster_uses_synthetic(tmp_path):
    app = _app(_settings(tmp_path))
    client = TestClient(app)
    version_id = "55555555-5555-4555-8555-555555555555"
    resp = client.post(
        "/internal/engine/jobs",
        json=_platform_job(baseline_version_id=version_id, task_id="66666666-6666-4666-8666-666666666666"),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "succeeded", data.get("error_message")
    meta = data["product"]["metadata"]
    assert meta["flood_event_status"] == "computed"
    assert meta["baseline_version_id"] == version_id
    assert meta["flood_event_ha"] is not None
    assert meta["extras"]["mock"] is True


def test_snap_mode_missing_gpt_does_not_fall_back_to_mock(tmp_path):
    app = _app(_settings(tmp_path, mode="snap"))
    client = TestClient(app)
    resp = client.post("/internal/engine/jobs", json=_platform_job())
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "failed"
    assert data["execution_mode"] == "snap"
    assert data["error_code"] == "GPT_NOT_FOUND"
    assert "不会改走 mock" in (data["error_message"] or "")
    assert data["product"] in (None, {})


def test_background_worker_drains_mock_job(tmp_path):
    settings = _settings(tmp_path, run_inline=False, worker=True)
    app = _app(settings)
    stop, thread = start_background_worker(app.state.worker, poll_seconds=0.05)
    client = TestClient(app)
    try:
        resp = client.post("/internal/engine/jobs", json=_platform_job())
        assert resp.status_code == 200, resp.text
        job_id = resp.json()["id"]
        status = resp.json()["status"]
        for _ in range(50):
            if status in {"succeeded", "failed"}:
                break
            time.sleep(0.1)
            status = client.get(f"/internal/engine/jobs/{job_id}").json()["status"]
        assert status == "succeeded"
    finally:
        stop.set()
        thread.join(timeout=2)


def test_unauthenticated_health(tmp_path):
    app = _app(_settings(tmp_path, run_inline=False))
    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["mode"] == "mock"
    assert resp.json()["status"] == "ok"
