
from __future__ import annotations

from sarap_engine.api.service import EngineService
from sarap_engine.products.ingest import IngestClient
from sarap_engine.orchestration.worker import Worker


def _body(**kw):
    base = {
        "scene_id": "SCENE-A",
        "pilot_id": "pilot_demo",
        "execution_mode": "mock",
        "scene": {"scene_id": "SCENE-A", "polarizations": ["VV"]},
        "pilot": {"pilot_id": "pilot_demo", "analysis_crs": "EPSG:4548"},
    }
    base.update(kw)
    return base


def test_duplicate_submit_returns_existing_job(store, settings):
    settings.run_inline = False
    svc = EngineService(store, settings, Worker(store, settings, ingest_client=IngestClient("http://x", mode="mock")))
    first, reused = svc.submit(_body())
    assert reused is False
    second, reused = svc.submit(_body())
    assert reused is True
    assert second["id"] == first["id"]
    assert second["reused"] is True


def test_force_rerun_creates_new_job(store, settings):
    settings.run_inline = False
    svc = EngineService(store, settings, Worker(store, settings, ingest_client=IngestClient("http://x", mode="mock")))
    first, _ = svc.submit(_body())
    second, reused = svc.submit(_body(force_rerun=True))
    assert reused is False
    assert second["id"] != first["id"]
    assert second["idempotency_key"] == first["idempotency_key"]


def test_different_baseline_is_different_key(store, settings):
    settings.run_inline = False
    svc = EngineService(store, settings, Worker(store, settings, ingest_client=IngestClient("http://x", mode="mock")))
    a, _ = svc.submit(_body())
    b, reused = svc.submit(_body(baseline_version_id="v2026.06.01"))
    assert reused is False
    assert a["id"] != b["id"]



def test_submit_accepts_platform_payload_without_pilot_id(store, settings):
    settings.run_inline = False
    from sarap_engine.api.service import EngineService
    from sarap_engine.products.ingest import IngestClient
    from sarap_engine.orchestration.worker import Worker

    svc = EngineService(store, settings, Worker(store, settings, ingest_client=IngestClient("http://x", mode="mock")))
    data, reused = svc.submit(
        {
            "task_id": "11111111-1111-4111-8111-111111111111",
            "scene_id": "22222222-2222-4222-8222-222222222222",
            "scene_code": "flood",
            "area_id": "33333333-3333-4333-8333-333333333333",
            "s1_product_id": "S1A_IW_GRD__1SDV_20260701T100000_20260701T100025_000001_000AAA_0000",
            "acquisition_start": "2026-07-01T10:00:00Z",
            "acquisition_end": "2026-07-01T10:00:25Z",
            "is_pilot": True,
            "execution_mode": "mock",
            "params": {
                "pilot": {
                    "analysis_crs": "EPSG:4548",
                    "grid": {"res_m": 10, "origin_x": 0, "origin_y": 0, "width": 80, "height": 80},
                }
            },
        }
    )
    assert reused is False
    assert data["area_id"] == "33333333-3333-4333-8333-333333333333"
    assert data["scene_id"] == "22222222-2222-4222-8222-222222222222"
    assert data["s1_product_id"].startswith("S1A_IW_GRD")
    assert data["task_id"] == "11111111-1111-4111-8111-111111111111"


def test_different_s1_product_is_different_key(store, settings):
    settings.run_inline = False
    from sarap_engine.api.service import EngineService
    from sarap_engine.products.ingest import IngestClient
    from sarap_engine.orchestration.worker import Worker

    svc = EngineService(store, settings, Worker(store, settings, ingest_client=IngestClient("http://x", mode="mock")))
    body = {
        "scene_id": "22222222-2222-4222-8222-222222222222",
        "area_id": "33333333-3333-4333-8333-333333333333",
        "s1_product_id": "S1A_PROD_A",
        "execution_mode": "mock",
    }
    a, _ = svc.submit(body)
    b, reused = svc.submit({**body, "s1_product_id": "S1A_PROD_B"})
    assert reused is False
    assert a["id"] != b["id"]
