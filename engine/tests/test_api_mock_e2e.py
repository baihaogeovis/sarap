
from __future__ import annotations

import json
from pathlib import Path

import httpx
import numpy as np
from fastapi.testclient import TestClient

from sarap_engine.config import Settings
from sarap_engine.constants import LIMITATIONS, ClassCode
from sarap_engine.main import create_app
from sarap_engine.orchestration.store import JobStore
from sarap_engine.orchestration.worker import Worker
from sarap_engine.products.ingest import IngestClient
from sarap_engine.products.raster_io import read_raster


def _app(tmp_path, ingest_transport=None):
    settings = Settings(
        mode="mock",
        work_dir=tmp_path / "work",
        db_url="sqlite:///:memory:",
        ingest_mode="http" if ingest_transport else "mock",
        platform_ingest_url="http://platform.test/api/v1/internal/products",
        run_inline=True,
    )
    store = JobStore(settings.db_url)
    ingest = IngestClient(
        settings.platform_ingest_url,
        internal_token="test-internal-token",
        mode="http" if ingest_transport else "mock",
        transport=ingest_transport,
    )
    worker = Worker(store, settings, ingest_client=ingest)
    app = create_app(settings, store)
    app.state.worker = worker
    app.state.service.worker = worker
    app.state.settings = settings
    return app, settings


def _payload(*, with_baseline: bool = False, mode: str = "mock", task_id: str | None = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"):
    acq = "2026-07-01T10:00:00Z"
    ready = "2026-07-01T11:00:00Z"
    return {
        "task_id": task_id,
        "scene_id": "S1A_IW_GRD_DEMO_20260701T1000",
        "pilot_id": "pilot_demo",
        "execution_mode": mode,
        "data_ready_at": ready,
        "use_synthetic_baseline": with_baseline,
        "baseline_version_id": "v2026.06.01" if with_baseline else None,
        "baseline_type": "permanent_water" if with_baseline else None,
        "scene": {
            "scene_id": "S1A_IW_GRD_DEMO_20260701T1000",
            "platform": "S1A",
            "polarizations": ["VV", "VH"],
            "ipf_version": "3.80",
            "acquisition_start": acq,
            "acquisition_end": "2026-07-01T10:00:25Z",
            "data_ready_at": ready,
        },
        "pilot": {
            "pilot_id": "pilot_demo",
            "name": "示例区域",
            "analysis_crs": "EPSG:4548",
            "grid": {"res_m": 10, "origin_x": 0, "origin_y": 0, "width": 80, "height": 80},
            "suggested_target_minutes": 240,
        },
    }


class _IngestHandler(httpx.MockTransport):
    def __init__(self):
        self.calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content.decode()) if request.content else {}
            record = {
                "method": request.method,
                "url": str(request.url),
                "path": request.url.path,
                "headers": dict(request.headers),
                "body": body,
            }
            self.calls.append(record)
            if request.url.path.endswith("/products"):
                return httpx.Response(201, json={"data": {"id": "prod-1", "status": "draft"}, "error": None})
            return httpx.Response(200, json={"data": {"status": body.get("status", "running")}, "error": None})

        super().__init__(handler)


def test_health(tmp_path):
    app, _ = _app(tmp_path)
    client = TestClient(app)
    resp = client.get("/internal/engine/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["spec_version"] == "1.1.0"


def test_mock_e2e_without_baseline(tmp_path):
    transport = _IngestHandler()
    app, _ = _app(tmp_path, ingest_transport=transport)
    client = TestClient(app)
    resp = client.post("/internal/engine/jobs", json=_payload(with_baseline=False))
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "succeeded"
    assert data["reused"] is False
    assert data["data_ready_at"]
    assert data["submitted_at"]
    assert data["processed_at"]
    product = data["product"]
    assert product
    meta = product["metadata"]
    assert meta["flood_event_status"] == "baseline_missing"
    assert meta["extracted_water_ha"] is not None
    assert meta["extracted_water_area_label"] == "提取水体面积（未扣本底）"
    assert meta["flood_event_ha"] is None
    assert meta["data_ready_at"]
    assert meta["submitted_at"]
    assert meta["processed_at"]
    assert meta["suggested_target_minutes"] == 240
    assert meta["external_target_hours"] == 4
    assert meta["contract_commitment"] is False
    for line in LIMITATIONS:
        assert line in meta["limitations"]
    layer_names = {ly["name"] for ly in product["layers"]}
    assert {"class_map", "water_current", "water_current_poly", "qc_flags", "qc_summary", "metadata"}.issubset(layer_names)
    # 空的本次淹没层允许存在，但必须标记 empty
    flood_layers = [ly for ly in product["layers"] if ly["name"] in {"flood_event", "flood_event_poly"}]
    assert flood_layers and all(ly.get("empty") for ly in flood_layers)
    qc = product["qc_summary"]
    assert "threshold_vv_db" in qc
    assert qc["flood_event_status"] == "baseline_missing"
    assert transport.calls, "应调用平台回传接口"
    product_calls = [c for c in transport.calls if c["path"].endswith("/products")]
    event_calls = [c for c in transport.calls if c["path"].endswith("/events") or c["path"].endswith("/progress")]
    assert product_calls, "应 POST /api/v1/internal/products"
    assert event_calls, "应回传任务事件或进度"
    ingest_body = product_calls[0]["body"]
    assert ingest_body["task_id"] == "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
    assert ingest_body["flood_event_status"] == "baseline_missing"
    assert ingest_body["extracted_water_ha"] is not None
    assert "flood_event_ha" not in ingest_body
    assert "sla_minutes" not in ingest_body
    assert "sla_minutes" not in ingest_body["metadata_json"]
    assert ingest_body["metadata_json"]["suggested_target_minutes"] == 240
    assert ingest_body["metadata_json"]["contract_commitment"] is False
    layer_keys = {item["layer_key"] for item in ingest_body["artifacts_json"]}
    assert "flood_event" not in layer_keys
    assert "flood_event_poly" not in layer_keys
    assert "X-internal-token" in product_calls[0]["headers"] or "x-internal-token" in product_calls[0]["headers"]

    # 读 class_map：无本底应为 5，不得出现 2/3
    class_layer = next(ly for ly in product["layers"] if ly["name"] == "class_map")
    arr, _grid = read_raster(Path(class_layer["uri"]))
    uniq = set(int(v) for v in np.unique(arr))
    assert ClassCode.EXTRACTED_WATER in uniq
    assert ClassCode.PERMANENT_OR_BASELINE_WATER not in uniq
    assert ClassCode.FLOOD_EVENT not in uniq
    # 建成区降级应产生低置信
    assert ClassCode.WATER_LOWCONF in uniq

    # GET 查询
    got = client.get(f"/internal/engine/jobs/{data['id']}")
    assert got.status_code == 200
    assert got.json()["status"] == "succeeded"


def test_mock_e2e_with_baseline(tmp_path):
    app, _ = _app(tmp_path)
    client = TestClient(app)
    resp = client.post("/internal/engine/jobs", json=_payload(with_baseline=True))
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "succeeded"
    meta = data["product"]["metadata"]
    assert meta["flood_event_status"] == "computed"
    assert meta["baseline_version_id"] == "v2026.06.01"
    assert meta["water_current_ha"] is not None
    assert meta["flood_event_ha"] is not None
    assert meta.get("extracted_water_area_label") in (None, "")
    class_layer = next(ly for ly in data["product"]["layers"] if ly["name"] == "class_map")
    arr, _ = read_raster(Path(class_layer["uri"]))
    uniq = set(int(v) for v in np.unique(arr))
    assert ClassCode.EXTRACTED_WATER not in uniq
    assert ClassCode.FLOOD_EVENT in uniq or ClassCode.PERMANENT_OR_BASELINE_WATER in uniq
    flood = next(ly for ly in data["product"]["layers"] if ly["name"] == "flood_event")
    assert not flood.get("empty")
    impact = data["product"]["impact_stats"]
    assert impact["cross_stats"] == []
    assert "未配置影响对象" in impact["cross_stats_note"]


def test_mock_e2e_with_public_validation_impacts(tmp_path):
    transport = _IngestHandler()
    app, _ = _app(tmp_path, ingest_transport=transport)
    client = TestClient(app)
    payload = _payload(with_baseline=True)
    payload["pilot"]["impact_assets"] = {
        "admin_county": "fixture:public_validation_window",
        "admin_township": "fixture:public_validation_window",
        "road": "fixture:public_validation_window",
        "settlement": "fixture:public_validation_window",
    }
    resp = client.post("/internal/engine/jobs", json=payload)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "succeeded", data.get("error_message")
    impact = data["product"]["impact_stats"]
    assert impact["cross_stats"]
    assert "未配置影响对象" not in impact["cross_stats_note"]
    roads = [row for row in impact["cross_stats"] if row["object_id"] == "rd-cross" and row["metric"] == "affected_length_m"]
    assert roads and roads[0]["value"] > 0
    assert all(row["object_id"] != "rd-dry" for row in impact["cross_stats"])
    names = {layer["name"] for layer in data["product"]["layers"]}
    assert "impact_road" in names
    assert "impact_settlement" in names
    assert "impact_admin_poly" in names
    assert "emergency_map" in names
    assert "thematic_map" in names
    road = next(layer for layer in data["product"]["layers"] if layer["name"] == "impact_road")
    features = json.loads(Path(road["uri"]).read_text(encoding="utf-8"))["features"]
    flat = [value for feature in features for pt in feature["geometry"]["coordinates"] for value in pt]
    assert any(abs(value) > 90 for value in flat)
    body = next(call["body"] for call in transport.calls if call["path"].endswith("/products"))
    assert body["impact_stats"]["cross_stats"]
    assert body["flood_event_status"] == "computed"
    embedded = next(item for item in body["artifacts_json"] if item["layer_key"] == "impact_road")
    assert embedded["metadata_json"]["geojson"]["features"]
    assert embedded["metadata_json"]["crs"] == "EPSG:4548"
    emergency = next(item for item in body["artifacts_json"] if item["layer_key"] == "emergency_map")
    assert emergency["metadata_json"]["document"]["impact_configured"] is True
    assert emergency["metadata_json"]["document"]["basis_label"] == "本次淹没"
    blob = json.dumps(body)
    assert "water_depth" not in blob
    assert "flood_depth" not in blob


def test_snap_mode_without_gpt_via_api(tmp_path):
    app, _ = _app(tmp_path)
    client = TestClient(app)
    payload = _payload(with_baseline=False, mode="snap")
    # 给一个存在的假输入，避免先报 INPUT_MISSING
    fake = tmp_path / "fake.SAFE"
    fake.write_text("not-a-real-safe")
    payload["scene"]["input_uri"] = str(fake)
    resp = client.post("/internal/engine/jobs", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "failed"
    assert data["error_code"] == "GPT_NOT_FOUND"
    assert "不会改走 mock" in (data["error_message"] or "")


def test_pie_sar_rejected_via_api(tmp_path):
    app, _ = _app(tmp_path)
    client = TestClient(app)
    resp = client.post("/internal/engine/jobs", json=_payload(mode="pie_sar"))
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "failed"
    assert data["error_code"] == "PLUGIN_NOT_IMPLEMENTED"


def test_cancel_and_priority_endpoints(tmp_path):
    settings = Settings(
        mode="mock",
        work_dir=tmp_path / "work",
        db_url="sqlite:///:memory:",
        ingest_mode="mock",
        run_inline=False,
    )
    store = JobStore(settings.db_url)
    app = create_app(settings, store)
    client = TestClient(app)
    resp = client.post("/internal/engine/jobs", json=_payload())
    job_id = resp.json()["id"]
    assert resp.json()["status"] == "queued"
    pr = client.post(f"/internal/engine/jobs/{job_id}/priority", json={"priority": "emergency"})
    assert pr.status_code == 200
    assert pr.json()["priority"] == "emergency"
    c = client.post(f"/internal/engine/jobs/{job_id}/cancel")
    assert c.status_code == 200
    assert c.json()["status"] == "cancelled"
