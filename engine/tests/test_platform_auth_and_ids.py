
"""平台鉴权环境变量与入站 token 对齐。"""

from __future__ import annotations

from fastapi.testclient import TestClient

from sarap_engine.config import Settings
from sarap_engine.main import create_app
from sarap_engine.orchestration.store import JobStore


def test_settings_read_platform_env_names(monkeypatch):
    monkeypatch.setenv("SARAP_INTERNAL_TOKEN", "plat-internal")
    monkeypatch.setenv("SARAP_ENGINE_TOKEN", "engine-inbound")
    settings = Settings(internal_token="legacy-engine-internal")
    assert settings.outbound_internal_token() == "plat-internal"
    assert settings.inbound_token() == "engine-inbound"


def test_engine_accepts_bearer_or_internal_token(tmp_path, monkeypatch):
    monkeypatch.delenv("SARAP_ENGINE_TOKEN", raising=False)
    monkeypatch.delenv("SARAP_INTERNAL_TOKEN", raising=False)
    settings = Settings(
        mode="mock",
        work_dir=tmp_path / "work",
        db_url="sqlite:///:memory:",
        ingest_mode="mock",
        run_inline=False,
        internal_token="engine-inbound",
    )
    app = create_app(settings, JobStore(settings.db_url))
    client = TestClient(app)
    body = {
        "task_id": "11111111-1111-4111-8111-111111111111",
        "scene_id": "22222222-2222-4222-8222-222222222222",
        "scene_code": "flood",
        "area_id": "33333333-3333-4333-8333-333333333333",
        "s1_product_id": "S1A_IW_GRD_DEMO",
        "execution_mode": "mock",
    }
    denied = client.post("/internal/engine/jobs", json=body)
    assert denied.status_code == 401
    ok_header = client.post("/internal/engine/jobs", json=body, headers={"X-Internal-Token": "engine-inbound"})
    assert ok_header.status_code == 200
    ok_bearer = client.post(
        "/internal/engine/jobs",
        json={**body, "s1_product_id": "S1A_IW_GRD_DEMO_2", "force_rerun": True},
        headers={"Authorization": "Bearer engine-inbound"},
    )
    assert ok_bearer.status_code == 200
