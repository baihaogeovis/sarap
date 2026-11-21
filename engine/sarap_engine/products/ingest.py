"""通过平台内部 HTTP 回传任务事件、进度与产品成果。引擎不 import 平台业务库，也不自己发布。"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from sarap_engine.constants import EngineError, ErrorCode, FloodEventStatus
from sarap_engine.products.models import ProductManifest

FLOOD_EVENT_LAYERS = {"flood_event", "flood_event_poly"}
DEPTH_KEY_FRAGMENTS = ("depth", "water_depth", "flood_depth")
HARD_ERROR_CODES = {"PROCESSING_FAILED", "GRID_MISALIGNED", "COVERAGE_TOO_LOW"}
# Vector layers travel with the ingest body so the platform can serve them
# without sharing the engine work directory. Rasters stay as URIs.
_MAX_EMBED_BYTES = 2_000_000


def _is_uuid(value: str | None) -> bool:
    if not value:
        return False
    try:
        uuid.UUID(str(value))
        return True
    except (ValueError, TypeError, AttributeError):
        return False


def _iso_z(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    text = str(value)
    if text.endswith("+00:00"):
        return text[:-6] + "Z"
    return text


def _strip_depth(data: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in data.items()
        if not any(frag in str(key).lower() for frag in DEPTH_KEY_FRAGMENTS)
    }


def _as_uuid_field(value: str | None) -> str | None:
    return str(value) if _is_uuid(value) else None


def internal_root_from_url(url: str) -> str:
    """从平台根地址或完整 products URL 解析出 /api/v1/internal。"""
    text = (url or "").rstrip("/")
    if not text:
        return "http://localhost:8000/api/v1/internal"
    if text.endswith("/internal/products"):
        return text[: -len("/products")]
    if text.endswith("/internal"):
        return text
    parsed = urlparse(text)
    if parsed.path in {"", "/"}:
        return text + "/api/v1/internal"
    if parsed.path.rstrip("/").endswith("/api/v1"):
        return text + "/internal"
    return text


def map_platform_status(engine_status: str) -> str:
    if engine_status in {"succeeded", "failed", "cancelled"}:
        return engine_status
    if engine_status in {"accepted", "queued", "retry_wait", "preempted"}:
        return "queued" if engine_status in {"accepted", "queued"} else "running"
    return "running"


def map_progress(engine_status: str) -> int:
    return {
        "accepted": 0,
        "queued": 0,
        "preparing": 10,
        "snap_running": 30,
        "extracting": 60,
        "change_detecting": 70,
        "impact_mapping": 80,
        "qc": 90,
        "ingesting": 95,
        "succeeded": 100,
        "failed": 100,
        "cancelled": 100,
        "retry_wait": 20,
        "preempted": 20,
    }.get(engine_status, 0)


def map_error_code(code: str | None) -> str:
    if not code:
        return ""
    if code in HARD_ERROR_CODES:
        return code
    if code in {"GRID_MISALIGNED", "COVERAGE_TOO_LOW"}:
        return code
    if code in {
        "GPT_NOT_FOUND",
        "GPT_CRASH",
        "GPT_TIMEOUT",
        "SNAP_OUTPUT_INVALID",
        "INTERNAL",
        "DISK_ERROR",
        "INGEST_ERROR",
    }:
        return "PROCESSING_FAILED" if code != "INGEST_ERROR" else code
    return code


_EMBED_JSON_NAMES = {"emergency_map", "impact_stats"}


def _embed_json(layer_uri: str, name: str) -> dict[str, Any] | None:
    """Copy a small JSON sidecar into the ingest body so the platform need not share the work dir."""
    if name not in _EMBED_JSON_NAMES or not layer_uri:
        return None
    path = Path(layer_uri)
    if not path.is_file():
        return None
    try:
        if path.stat().st_size > _MAX_EMBED_BYTES:
            return None
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(doc, dict):
        return None
    return doc


def _strip_depth_tree(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _strip_depth_tree(item)
            for key, item in value.items()
            if not any(frag in str(key).lower() for frag in DEPTH_KEY_FRAGMENTS)
        }
    if isinstance(value, list):
        return [_strip_depth_tree(item) for item in value]
    return value


def _embed_vector(layer_uri: str, media_type: str) -> dict[str, Any] | None:
    """Read a GeoJSON layer from the engine work dir for the ingest payload."""
    looks_geo = media_type == "application/geo+json" or str(layer_uri).endswith(".geojson")
    if not looks_geo or not layer_uri:
        return None
    path = Path(layer_uri)
    if not path.is_file():
        return None
    try:
        if path.stat().st_size > _MAX_EMBED_BYTES:
            return None
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(doc, dict) or doc.get("type") != "FeatureCollection":
        return None
    return doc


def is_flood_product(product_type: str | None) -> bool:
    text = (product_type or "").upper()
    return "FLOOD" in text or text.startswith("SARAP_FLOOD")


def resolve_flood_event_status(status: str | None, *, product_type: str | None) -> str:
    """洪水任务出结果后只保留 computed / baseline_missing；none 仅用于未出结果或非洪水产品。"""
    raw = (status or "").strip() or FloodEventStatus.NONE.value
    if not is_flood_product(product_type):
        return raw
    if raw in {FloodEventStatus.COMPUTED.value, FloodEventStatus.BASELINE_MISSING.value}:
        return raw
    return FloodEventStatus.BASELINE_MISSING.value


class IngestClient:
    def __init__(
        self,
        base_url: str,
        *,
        token: str = "",
        internal_token: str = "",
        api_key: str = "",
        mode: str = "http",
        timeout: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.internal_root = internal_root_from_url(base_url)
        self.token = token
        self.internal_token = internal_token or token
        self.api_key = api_key
        self.mode = mode
        self.timeout = timeout
        self.transport = transport
        self.calls: list[dict[str, Any]] = []

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        # 回传平台：X-Internal-Token = SARAP_INTERNAL_TOKEN；服务账号只用 X-API-Key。
        # Bearer 只接受 JWT，不要把原始 API Key 放到 Authorization 里。
        if self.internal_token:
            headers["X-Internal-Token"] = self.internal_token
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        return headers

    def _request(self, method: str, url: str, payload: dict[str, Any], *, retryable_4xx: bool = False) -> dict[str, Any]:
        self.calls.append({"method": method, "url": url, "body": payload})
        if self.mode == "mock":
            return {"status": "accepted", "mode": "mock"}
        try:
            with httpx.Client(timeout=self.timeout, transport=self.transport) as client:
                resp = client.request(method, url, json=payload, headers=self._headers())
        except httpx.HTTPError as exc:
            raise EngineError(ErrorCode.INGEST_ERROR, f"平台回传失败: {exc}", retryable=True) from exc

        if 500 <= resp.status_code < 600:
            raise EngineError(
                ErrorCode.INGEST_ERROR,
                f"平台回传 5xx: {resp.status_code} {resp.text[:300]}",
                retryable=True,
            )
        if resp.status_code >= 400:
            raise EngineError(
                ErrorCode.INGEST_ERROR,
                f"平台回传被拒绝: {resp.status_code} {resp.text[:300]}",
                retryable=retryable_4xx,
            )
        try:
            return resp.json()
        except ValueError:
            return {"status": "accepted", "raw": resp.text[:500]}

    def post_progress(self, task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.internal_root}/tasks/{task_id}/progress"
        return self._request("POST", url, payload)

    def post_event(self, task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.internal_root}/tasks/{task_id}/events"
        return self._request("POST", url, payload)

    def notify_task(self, task_id: str | None, *, status: str, error_code: str | None = None, error_message: str | None = None, log_uri: str | None = None, data_ready_at: Any = None, processed_at: Any = None) -> dict[str, Any] | None:
        if not task_id:
            return None
        platform_status = map_platform_status(status)
        body: dict[str, Any] = {
            "status": platform_status,
            "step": status,
            "progress": map_progress(status),
            "progress_json": {"engine_status": status, "step": status},
        }
        if error_code:
            body["error_code"] = map_error_code(error_code) if platform_status == "failed" else error_code
        if error_message:
            body["error_message"] = error_message
        if log_uri:
            body["log_uri"] = log_uri
        if data_ready_at:
            body["data_ready_at"] = _iso_z(data_ready_at)
        if processed_at:
            body["processed_at"] = _iso_z(processed_at)
        # 进度与事件语义一致，两边都打点，便于平台任一端点消费
        try:
            self.post_progress(task_id, {k: body[k] for k in ("progress", "progress_json", "step") if k in body})
            return self.post_event(task_id, body)
        except EngineError:
            # 运行中的进度失败不打断处理；终态失败由调用方决定
            if platform_status not in {"succeeded", "failed", "cancelled"}:
                return None
            raise

    def build_product_payload(self, job_id: str, manifest: ProductManifest, *, task_id: str, title: str | None = None) -> dict[str, Any]:
        metadata = manifest.metadata
        meta = _strip_depth(metadata.to_public_dict() if metadata else {})
        product_type = (metadata.product_type if metadata else None) or "SARAP_FLOOD_V1"
        status = resolve_flood_event_status(
            metadata.flood_event_status if metadata else None,
            product_type=product_type,
        )
        has_baseline = status == FloodEventStatus.COMPUTED.value
        if not has_baseline:
            meta = {key: value for key, value in meta.items() if not str(key).startswith("flood_event")}
            meta["flood_event_status"] = status
        source_crs = (metadata.crs if metadata else "") or ""
        artifacts: list[dict[str, Any]] = []
        for layer in manifest.layers:
            if layer.name in FLOOD_EVENT_LAYERS and not has_baseline:
                continue
            item: dict[str, Any] = {
                "layer_key": layer.name,
                "name": layer.name,
                "storage_uri": layer.uri,
                "uri": layer.uri,
                "media_type": layer.media_type,
                "empty": layer.empty,
            }
            layer_meta: dict[str, Any] = {}
            if source_crs:
                layer_meta["crs"] = source_crs
            if layer.empty:
                layer_meta["empty"] = True
            if layer.note:
                layer_meta["note"] = layer.note
            embedded = _embed_vector(layer.uri, layer.media_type)
            if embedded is not None:
                layer_meta["geojson"] = embedded
            document = _embed_json(layer.uri, layer.name)
            if document is not None:
                layer_meta["document"] = _strip_depth_tree(document)
            if layer_meta:
                item["metadata_json"] = layer_meta
            artifacts.append(item)
        qc_warnings: list[str] = []
        if isinstance(manifest.qc_summary, dict):
            raw = manifest.qc_summary.get("warnings") or manifest.qc_summary.get("qc_warnings") or []
            qc_warnings = [str(item) for item in raw]
            meta.setdefault("qc_summary", manifest.qc_summary)

        extracted = metadata.extracted_water_ha if metadata else None
        water_current = metadata.water_current_ha if metadata else None
        flood_event_ha = metadata.flood_event_ha if metadata else None
        lowconf = metadata.lowconf_ha if metadata else None
        baseline_version = ""
        baseline_version_id = None
        baseline_asset_id = None
        if metadata:
            if metadata.baseline_version_id and _is_uuid(metadata.baseline_version_id):
                baseline_version_id = metadata.baseline_version_id
            elif metadata.baseline_version_id:
                baseline_version = metadata.baseline_version_id
            baseline_asset_id = _as_uuid_field(metadata.baseline_asset_id)

        payload: dict[str, Any] = {
            "task_id": task_id,
            "product_type": product_type,
            "title": title or (metadata.product_id if metadata else "SARAP 洪水准范围"),
            "code": metadata.product_id if metadata else None,
            "storage_uri": manifest.work_dir or "",
            "artifacts_json": artifacts,
            "metadata_json": meta,
            "engine_name": "sarap_engine",
            "engine_params_json": {"engine_job_id": job_id},
            "baseline_version": baseline_version,
            "baseline_version_id": baseline_version_id,
            "baseline_asset_id": baseline_asset_id,
            "flood_event_status": status,
            "processed_at": _iso_z(metadata.processed_at if metadata else None),
            "acquisition_start": _iso_z(metadata.acquisition_start if metadata else None),
            "acquisition_end": _iso_z(metadata.acquisition_end if metadata else None),
            "s1_product_id": (metadata.s1_product_id if metadata else None) or "",
            "qc_warnings": qc_warnings,
            "lowconf_ha": lowconf,
            "impact_stats": _strip_depth_tree(dict(manifest.impact_stats or {})),
        }
        if has_baseline:
            payload["water_current_ha"] = water_current
            payload["flood_event_ha"] = flood_event_ha
            payload["extracted_water_ha"] = None
        else:
            payload["extracted_water_ha"] = extracted
            payload["water_current_ha"] = None
            # 缺本底不要回传 flood_event*
        nested = meta.get("extras") if isinstance(meta.get("extras"), dict) else {}
        imagery_dataset_id = _as_uuid_field(str(nested.get("imagery_dataset_id") or "") or None)
        if imagery_dataset_id:
            payload["imagery_dataset_id"] = imagery_dataset_id
        return payload

    def ingest(self, job_id: str, manifest: ProductManifest, *, task_id: str | None = None, title: str | None = None) -> dict[str, Any]:
        if not task_id:
            if self.mode == "mock":
                return {"status": "accepted", "mode": "mock", "product_id": manifest.product_id, "skipped": "no_task_id"}
            raise EngineError(ErrorCode.INGEST_ERROR, "入库缺少平台 task_id，无法调用 /internal/products", retryable=False)

        payload = self.build_product_payload(job_id, manifest, task_id=task_id, title=title)
        if self.mode == "mock":
            self.calls.append({"method": "POST", "url": f"{self.internal_root}/products", "body": payload})
            return {"status": "accepted", "mode": "mock", "product_id": manifest.product_id, "payload": payload}

        url = f"{self.internal_root}/products"
        return self._request("POST", url, payload)
