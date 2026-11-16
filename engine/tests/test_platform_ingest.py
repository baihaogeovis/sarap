"""平台内部回传契约：products / events / progress，不含水深，不用 sla 合同字段。"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import httpx

from sarap_engine.constants import FloodEventStatus
from sarap_engine.products.ingest import IngestClient, map_error_code, map_platform_status
from sarap_engine.products.models import ProductLayer, ProductManifest, ProductMetadata


def _manifest(*, has_baseline: bool) -> ProductManifest:
    status = FloodEventStatus.COMPUTED.value if has_baseline else FloodEventStatus.BASELINE_MISSING.value
    layers = [
        ProductLayer(name="class_map", uri="file://class_map.tif", media_type="image/tiff"),
        ProductLayer(name="water_current", uri="file://water_current.tif", media_type="image/tiff"),
        ProductLayer(name="flood_event", uri="file://flood_event.tif", media_type="image/tiff", empty=not has_baseline),
        ProductLayer(name="flood_event_poly", uri="file://flood_event_poly.geojson", empty=not has_baseline),
        ProductLayer(name="metadata", uri="file://metadata.json", media_type="application/json"),
    ]
    meta = ProductMetadata(
        product_id="SARAP_FLOOD_DEMO",
        pilot_id="pilot_demo",
        scene_id="S1A_DEMO",
        processed_at=datetime(2026, 11, 14, 0, 0, tzinfo=timezone.utc),
        data_ready_at=datetime(2026, 11, 13, 20, 0, tzinfo=timezone.utc),
        submitted_at=datetime(2026, 11, 13, 20, 10, tzinfo=timezone.utc),
        suggested_target_minutes=240,
        sla_minutes=240,
        contract_commitment=False,
        flood_event_status=status,
        extracted_water_ha=None if has_baseline else 8.5,
        water_current_ha=12.0 if has_baseline else 8.5,
        flood_event_ha=3.2 if has_baseline else None,
        baseline_version_id="v2026.06.01" if has_baseline else None,
        extras={"water_depth_m": 1.23},
    )
    return ProductManifest(product_id=meta.product_id, layers=layers, metadata=meta, work_dir="/tmp/prod")


def test_payload_without_baseline_omits_flood_layers_and_depth():
    client = IngestClient("http://platform.test/api/v1/internal/products", mode="mock")
    payload = client.build_product_payload("job-1", _manifest(has_baseline=False), task_id="11111111-1111-4111-8111-111111111111")
    assert payload["task_id"] == "11111111-1111-4111-8111-111111111111"
    assert payload["flood_event_status"] == "baseline_missing"
    assert payload["extracted_water_ha"] == 8.5
    assert "flood_event_ha" not in payload
    assert payload["water_current_ha"] is None
    assert not any(str(k).startswith("flood_event") and k != "flood_event_status" for k in payload)
    assert not any(str(k).startswith("flood_event") and k != "flood_event_status" for k in payload["metadata_json"])
    keys = {item["layer_key"] for item in payload["artifacts_json"]}
    assert "flood_event" not in keys
    assert "class_map" in keys
    assert "sla_minutes" not in payload
    assert "sla_minutes" not in payload["metadata_json"]
    assert payload["metadata_json"]["suggested_target_minutes"] == 240
    assert payload["metadata_json"]["contract_commitment"] is False
    assert "water_depth_m" not in payload["metadata_json"]
    assert payload["metadata_json"]["data_ready_at"].endswith("Z")
    assert payload["baseline_version_id"] is None  # 非 UUID 不得塞进 uuid 字段


def test_payload_with_baseline_includes_flood_areas():
    client = IngestClient("http://localhost:8000", mode="mock")
    payload = client.build_product_payload("job-2", _manifest(has_baseline=True), task_id="11111111-1111-4111-8111-111111111111")
    assert payload["flood_event_status"] == "computed"
    assert payload["extracted_water_ha"] is None
    assert payload["water_current_ha"] == 12.0
    assert payload["flood_event_ha"] == 3.2
    keys = {item["layer_key"] for item in payload["artifacts_json"]}
    assert "flood_event" in keys
    assert payload["baseline_version"] == "v2026.06.01"
    assert payload["baseline_version_id"] is None


def test_http_posts_products_events_progress_with_internal_token():
    recorded = []

    def handler(request: httpx.Request) -> httpx.Response:
        recorded.append((request.method, request.url.path, dict(request.headers), json.loads(request.content.decode())))
        if request.url.path.endswith("/products"):
            return httpx.Response(201, json={"data": {"status": "draft"}})
        return httpx.Response(200, json={"data": {"status": "running"}})

    client = IngestClient(
        "http://platform.test/api/v1/internal/products",
        internal_token="secret-token",
        mode="http",
        transport=httpx.MockTransport(handler),
    )
    task_id = "11111111-1111-4111-8111-111111111111"
    client.notify_task(task_id, status="snap_running")
    client.ingest("job-1", _manifest(has_baseline=False), task_id=task_id)
    paths = [path for _, path, _, _ in recorded]
    assert "/api/v1/internal/tasks/11111111-1111-4111-8111-111111111111/progress" in paths
    assert "/api/v1/internal/tasks/11111111-1111-4111-8111-111111111111/events" in paths
    assert "/api/v1/internal/products" in paths
    product = next(body for _, path, _, body in recorded if path.endswith("/products"))
    headers = next(hdrs for _, path, hdrs, _ in recorded if path.endswith("/products"))
    assert headers.get("x-internal-token") == "secret-token"
    assert product["flood_event_status"] == "baseline_missing"


def test_status_and_hard_error_mapping():
    assert map_platform_status("extracting") == "running"
    assert map_platform_status("succeeded") == "succeeded"
    assert map_error_code("GRID_MISALIGNED") == "GRID_MISALIGNED"
    assert map_error_code("GPT_CRASH") == "PROCESSING_FAILED"



def test_api_key_is_not_sent_as_bearer():
    recorded = []

    def handler(request: httpx.Request) -> httpx.Response:
        recorded.append(dict(request.headers))
        return httpx.Response(200, json={"ok": True})

    client = IngestClient(
        "http://platform.test",
        api_key="plain-api-key",
        mode="http",
        transport=httpx.MockTransport(handler),
    )
    client.post_progress("11111111-1111-4111-8111-111111111111", {"progress": 10, "step": "preparing"})
    headers = recorded[0]
    assert headers.get("x-api-key") == "plain-api-key"
    assert "authorization" not in headers


def test_flood_status_none_coerced_for_completed_flood_product():
    manifest = _manifest(has_baseline=False)
    manifest.metadata.flood_event_status = "none"
    client = IngestClient("http://platform.test", mode="mock")
    payload = client.build_product_payload(
        "job-1", manifest, task_id="11111111-1111-4111-8111-111111111111"
    )
    assert payload["flood_event_status"] == "baseline_missing"
    assert "flood_event_ha" not in payload
    assert "flood_event" not in {item["layer_key"] for item in payload["artifacts_json"]}
