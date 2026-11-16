"""任务提交、查询、取消、插队与幂等。"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sarap_engine import PRODUCT_VERSION, SPEC_VERSION, __version__
from sarap_engine.config import Settings, get_settings
from sarap_engine.constants import (
    DEFAULT_ALGO_PROFILE_ID,
    ErrorCode,
    ExecutionMode,
    JobStatus,
    Priority,
)
from sarap_engine.domain.algo_profile import load_default_profile
from sarap_engine.orchestration.models import JobRow, job_to_dict, new_job_id, utcnow
from sarap_engine.orchestration.state_machine import is_terminal
from sarap_engine.orchestration.store import JobStore
from sarap_engine.orchestration.worker import Worker
from sarap_engine.plugins.snap.runner import find_gpt


def _first(*values: Any) -> Any:
    for value in values:
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        return value
    return None


def compute_idempotency_key(
    *,
    scene_id: str,
    area_id: str,
    s1_product_id: str | None,
    baseline_version_id: str | None,
    algo_profile_id: str,
    param_hash: str,
) -> str:
    base = baseline_version_id or ""
    s1 = s1_product_id or ""
    return f"{scene_id}|{area_id}|{s1}|{base}|{algo_profile_id}|{param_hash}"


class EngineService:
    def __init__(self, store: JobStore, settings: Settings | None = None, worker: Worker | None = None) -> None:
        self.store = store
        self.settings = settings or get_settings()
        self.worker = worker or Worker(store, self.settings)

    def submit(self, body: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        params = body.get("params") or {}
        if not isinstance(params, dict):
            params = {}
        scene = body.get("scene") or params.get("scene") or {}
        pilot = body.get("pilot") or params.get("pilot") or {}
        if not isinstance(scene, dict):
            scene = {}
        if not isinstance(pilot, dict):
            pilot = {}
        area_config = params.get("area_config") if isinstance(params.get("area_config"), dict) else {}
        # 平台把区域分析 CRS / 网格放在 params 里。没有显式 pilot 时从这里抬上来，
        # 避免退回引擎默认 CRS，也不要在引擎里写死某一条流域。
        if not pilot.get("analysis_crs"):
            crs = _first(params.get("analysis_crs"), area_config.get("analysis_crs"))
            if crs:
                pilot["analysis_crs"] = crs
        if not pilot.get("exchange_crs") and area_config.get("exchange_crs"):
            pilot["exchange_crs"] = area_config["exchange_crs"]
        if not pilot.get("grid") and isinstance(params.get("grid"), dict):
            pilot["grid"] = params["grid"]
        if not pilot.get("aoi_wkt"):
            wkt = _first(params.get("aoi_wkt"), area_config.get("aoi_wkt"))
            if wkt:
                pilot["aoi_wkt"] = wkt
        if not pilot.get("name"):
            name = _first(params.get("area_name"), area_config.get("name"))
            if name:
                pilot["name"] = name
        if not pilot.get("overrides") and isinstance(area_config.get("overrides"), dict):
            pilot["overrides"] = area_config["overrides"]
        if not pilot.get("algo_profile_id") and area_config.get("algo_profile_id"):
            pilot["algo_profile_id"] = area_config["algo_profile_id"]
        if "suggested_target_minutes" not in pilot and area_config.get("suggested_target_minutes"):
            pilot["suggested_target_minutes"] = area_config["suggested_target_minutes"]
        scene_id = _first(
            body.get("scene_id"),
            scene.get("scene_id"),
            params.get("scene_id"),
            body.get("scene_code"),
            scene.get("scene_code"),
            params.get("scene_code"),
        )
        scene_code = _first(body.get("scene_code"), scene.get("scene_code"), params.get("scene_code"))
        s1_product_id = _first(
            body.get("s1_product_id"),
            scene.get("s1_product_id"),
            params.get("s1_product_id"),
        )
        area_id = _first(
            body.get("area_id"),
            pilot.get("area_id"),
            params.get("area_id"),
            body.get("pilot_id"),  # 兼容旧调用
            pilot.get("pilot_id"),
            params.get("pilot_id"),
        )
        is_pilot = _first(body.get("is_pilot"), pilot.get("is_pilot"), params.get("is_pilot"))
        acquisition_start = _first(
            body.get("acquisition_start"),
            scene.get("acquisition_start"),
            params.get("acquisition_start"),
        )
        acquisition_end = _first(
            body.get("acquisition_end"),
            scene.get("acquisition_end"),
            params.get("acquisition_end"),
        )
        platform_task_id = body.get("task_id") or params.get("task_id") or ""
        if not area_id:
            raise ValueError("area_id 必填（区域是主对象；pilot_id 不是必填项）")
        if not scene_id and not s1_product_id:
            raise ValueError("需要平台 scene_id（或 scene_code）或 s1_product_id；scene_id 不是 Sentinel-1 PRODUCT-ID")
        scene = {
            **scene,
            "scene_id": scene_id or scene.get("scene_id") or "",
            "s1_product_id": s1_product_id,
            "scene_code": scene_code,
            "acquisition_start": acquisition_start,
            "acquisition_end": acquisition_end,
        }
        if body.get("data_ready_at") and not scene.get("data_ready_at"):
            scene["data_ready_at"] = body.get("data_ready_at")
        pilot = {
            **pilot,
            "area_id": area_id,
            "is_pilot": bool(is_pilot),
        }
        if body.get("pilot_id") or pilot.get("pilot_id"):
            pilot["pilot_id"] = _first(pilot.get("pilot_id"), body.get("pilot_id"))

        algo_profile_id = body.get("algo_profile_id") or pilot.get("algo_profile_id") or DEFAULT_ALGO_PROFILE_ID
        profile = load_default_profile()
        if algo_profile_id != profile.algo_profile_id:
            profile = profile.model_copy(update={"algo_profile_id": algo_profile_id})
        overrides = body.get("param_overrides") or pilot.get("overrides") or {}
        profile = profile.apply_overrides(overrides)
        param_hash = profile.param_hash()
        baseline_version_id = body.get("baseline_version_id") or params.get("baseline_version_id") or ""
        key = compute_idempotency_key(
            scene_id=str(scene_id or ""),
            area_id=str(area_id),
            s1_product_id=s1_product_id,
            baseline_version_id=baseline_version_id,
            algo_profile_id=profile.algo_profile_id,
            param_hash=param_hash,
        )
        force = bool(body.get("force_rerun"))
        existing = self.store.find_by_idempotency(key)
        if existing is not None and not force:
            data = job_to_dict(existing)
            data["reused"] = True
            return data, True

        mode = body.get("execution_mode") or self.settings.mode
        try:
            mode = ExecutionMode(mode).value
        except ValueError as exc:
            raise ValueError(f"非法 execution_mode: {mode}") from exc

        data_ready = body.get("data_ready_at") or scene.get("data_ready_at")
        if isinstance(data_ready, str):
            data_ready = datetime.fromisoformat(data_ready.replace("Z", "+00:00"))
        submitted = utcnow()
        job_id = new_job_id()
        work = self.settings.resolved_work_dir() / job_id
        work.mkdir(parents=True, exist_ok=True)

        extras = dict(body.get("extras") or params.get("extras") or {})
        if body.get("org_id"):
            extras["org_id"] = body.get("org_id")
        if body.get("project_id"):
            extras["project_id"] = body.get("project_id")
        if scene_code:
            extras["scene_code"] = scene_code
        if body.get("task_type"):
            extras["task_type"] = body.get("task_type")
        extras["area_id"] = area_id
        extras["is_pilot"] = bool(is_pilot)
        if s1_product_id:
            extras["s1_product_id"] = s1_product_id
        imagery_dataset_id = _first(params.get("imagery_dataset_id"), extras.get("imagery_dataset_id"))
        if imagery_dataset_id:
            extras["imagery_dataset_id"] = str(imagery_dataset_id)
        baseline_uri = body.get("baseline_uri") or params.get("baseline_uri")
        # mock 且只给了已发布本底版本、没有栅格文件时，用合成水体做对比。
        # snap / pie_sar 不走这条路：缺 gpt 仍是 GPT_NOT_FOUND，不会改走 mock。
        synthetic_flag = body.get("use_synthetic_baseline", params.get("use_synthetic_baseline"))
        if synthetic_flag is None:
            use_synthetic = bool(mode == ExecutionMode.MOCK.value and baseline_version_id and not baseline_uri)
        else:
            use_synthetic = bool(synthetic_flag)
        payload = {
            "scene": scene,
            "pilot": pilot,
            "area_id": area_id,
            "s1_product_id": s1_product_id,
            "is_pilot": bool(is_pilot),
            "baseline_uri": baseline_uri,
            "baseline_asset_id": body.get("baseline_asset_id") or params.get("baseline_asset_id"),
            "baseline_type": body.get("baseline_type") or params.get("baseline_type"),
            "param_overrides": overrides,
            "use_synthetic_baseline": use_synthetic,
            "platform_task_id": platform_task_id,
            "extras": extras,
            "params": params,
        }
        row = JobRow(
            id=job_id,
            status=JobStatus.ACCEPTED.value,
            priority=Priority(body.get("priority") or Priority.NORMAL).value,
            execution_mode=mode,
            idempotency_key=key,
            scene_id=str(scene_id or ""),
            area_id=str(area_id),
            s1_product_id=str(s1_product_id or ""),
            pilot_id=str(area_id),  # 兼容旧列；不再把试点当作区域主键
            baseline_version_id=baseline_version_id or "",
            algo_profile_id=profile.algo_profile_id,
            param_hash=param_hash,
            force_rerun=force,
            payload_json=json.dumps(payload, ensure_ascii=False, default=str),
            submitted_at=submitted,
            data_ready_at=data_ready,
            updated_at=submitted,
            work_dir=str(work),
            platform_task_id=str(platform_task_id or ""),
        )
        self.store.add(row)
        self.store.transition(job_id, JobStatus.QUEUED)
        if self.settings.run_inline:
            self.worker.execute(job_id)
        data = job_to_dict(self.store.get(job_id))
        data["reused"] = False
        return data, False

    def get(self, job_id: str) -> dict[str, Any] | None:
        row = self.store.get(job_id)
        return job_to_dict(row) if row else None

    def cancel(self, job_id: str) -> dict[str, Any]:
        row = self.store.get(job_id)
        if row is None:
            raise KeyError(job_id)
        if is_terminal(row.status):
            raise RuntimeError(f"任务已结束（{row.status}），无法取消")
        # 正在跑 gpt 时只打取消标记，等步骤边界再落地
        if row.status == JobStatus.SNAP_RUNNING.value:
            self.store.update(job_id, cancel_requested=True)
            return job_to_dict(self.store.get(job_id))
        self.store.update(job_id, cancel_requested=True)
        self.store.transition(
            job_id,
            JobStatus.CANCELLED,
            error_code=ErrorCode.CANCELLED.value,
            error_message="任务已取消",
            finished_at=utcnow(),
        )
        return job_to_dict(self.store.get(job_id))

    def set_priority(self, job_id: str, priority: str) -> dict[str, Any]:
        row = self.store.get(job_id)
        if row is None:
            raise KeyError(job_id)
        self.store.update(job_id, priority=Priority(priority).value)
        return job_to_dict(self.store.get(job_id))

    def health(self) -> dict[str, Any]:
        return {
            "status": "ok",
            "mode": self.settings.mode,
            "gpt_available": find_gpt(self.settings.gpt_binary) is not None,
            "version": __version__,
            "spec_version": SPEC_VERSION,
            "product_version": PRODUCT_VERSION,
        }
