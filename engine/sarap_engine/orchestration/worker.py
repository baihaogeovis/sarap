"""拉取并执行任务。步骤边界可被应急任务抢占；不 SIGKILL 正在跑的 gpt。"""

from __future__ import annotations

import json
import traceback
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from sarap_engine.config import Settings, get_settings
from sarap_engine.constants import (
    INTERNAL_BUDGET_MINUTES,
    EngineError,
    ErrorCode,
    ExecutionMode,
    JobStatus,
)
from sarap_engine.domain.algo_profile import load_default_profile
from sarap_engine.domain.pilot import PilotConfig
from sarap_engine.domain.scene import SceneMeta
from sarap_engine.orchestration.models import JobRow, utcnow
from sarap_engine.orchestration.preemption import should_preempt
from sarap_engine.orchestration.queue import JobQueue
from sarap_engine.orchestration.retry import decide_retry
from sarap_engine.orchestration.state_machine import is_terminal
from sarap_engine.orchestration.store import JobStore
from sarap_engine.plugins.base import PluginContext
from sarap_engine.plugins.registry import default_registry
from sarap_engine.plugins.snap.workflows.pipeline import run_postprocess
from sarap_engine.products.ingest import IngestClient

STEP_ORDER = [
    JobStatus.PREPARING,
    JobStatus.SNAP_RUNNING,
    JobStatus.EXTRACTING,
    JobStatus.CHANGE_DETECTING,
    JobStatus.IMPACT_MAPPING,
    JobStatus.QC,
    JobStatus.INGESTING,
]


class Worker:
    def __init__(
        self,
        store: JobStore,
        settings: Settings | None = None,
        *,
        ingest_client: IngestClient | None = None,
        step_hook: Callable[[JobRow, JobStatus], None] | None = None,
    ) -> None:
        self.store = store
        self.queue = JobQueue(store)
        self.settings = settings or get_settings()
        self.ingest_client = ingest_client or IngestClient(
            self.settings.platform_ingest_url or self.settings.platform_base_url,
            internal_token=self.settings.outbound_internal_token(),
            api_key=self.settings.platform_token,
            mode=self.settings.ingest_mode,
        )
        self.step_hook = step_hook
        self.registry = default_registry()

    def run_until_idle(self, *, max_jobs: int = 100) -> int:
        n = 0
        while n < max_jobs:
            row = self.queue.pop_next()
            if row is None:
                break
            self.execute(row.id)
            n += 1
        return n

    def execute(self, job_id: str) -> JobRow:
        row = self.store.get(job_id)
        if row is None:
            raise KeyError(job_id)
        if is_terminal(row.status):
            return row
        if row.status == JobStatus.RETRY_WAIT:
            self.store.transition(job_id, JobStatus.QUEUED)
            row = self.store.get(job_id)
        if row.status == JobStatus.QUEUED:
            self.store.transition(
                job_id,
                JobStatus.PREPARING,
                started_at=row.started_at or utcnow(),
            )
            self._notify_platform(job_id)
        return self._run_pipeline(job_id)

    def _fail_or_retry(self, job_id: str, err: EngineError | Exception) -> JobRow:
        if isinstance(err, EngineError):
            code, msg, retryable = err.code, err.message, err.retryable
        else:
            code, msg, retryable = ErrorCode.INTERNAL, f"{type(err).__name__}: {err}", True
        row = self.store.get(job_id)
        decision = decide_retry(
            code,
            general_retry_count=row.retry_count,
            snap_crash_retry_count=row.snap_crash_retry_count,
            max_retries=self.settings.max_retries,
            snap_immediate_retries=self.settings.snap_crash_immediate_retries,
            retry_base_seconds=self.settings.retry_base_seconds,
            retry_max_seconds=self.settings.retry_max_seconds,
            retryable_override=retryable if isinstance(err, EngineError) else None,
        )
        fields: dict[str, Any] = {
            "error_code": str(code.value if isinstance(code, ErrorCode) else code),
            "error_message": msg,
        }
        if decision.retry and decision.kind == "snap_immediate":
            fields["snap_crash_retry_count"] = row.snap_crash_retry_count + 1
            fields["retry_at"] = utcnow()
            out = self.store.transition(job_id, JobStatus.RETRY_WAIT, **fields)
            self._notify_platform(job_id)
            return out
        if decision.retry and decision.kind == "general":
            fields["retry_count"] = row.retry_count + 1
            fields["retry_at"] = utcnow() + timedelta(seconds=decision.delay_seconds)
            out = self.store.transition(job_id, JobStatus.RETRY_WAIT, **fields)
            self._notify_platform(job_id)
            return out
        fields["finished_at"] = utcnow()
        out = self.store.transition(job_id, JobStatus.FAILED, **fields)
        self._notify_platform(job_id, fatal=False)
        return out

    def _cancel_if_requested(self, job_id: str) -> bool:
        row = self.store.get(job_id)
        if row and row.cancel_requested and not is_terminal(row.status):
            self.store.transition(
                job_id,
                JobStatus.CANCELLED,
                error_code=ErrorCode.CANCELLED.value,
                error_message="任务已取消",
                finished_at=utcnow(),
            )
            self._notify_platform(job_id, fatal=False)
            return True
        return False

    def _maybe_preempt(self, job_id: str, status: JobStatus, *, gpt_running: bool = False) -> bool:
        row = self.store.get(job_id)
        if row is None:
            return False
        waiting = self.store.has_queued_emergency(exclude_id=job_id)
        if should_preempt(row.priority, status, emergency_waiting=waiting, gpt_running=gpt_running):
            checkpoint = {
                "last_completed_step": status.value,
                "preempted_at": utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
            self.store.transition(
                job_id,
                JobStatus.PREEMPTED,
                checkpoint_json=json.dumps(checkpoint, ensure_ascii=False),
            )
            # 回到 queued，保持原优先级（低于 emergency）
            self.store.transition(job_id, JobStatus.QUEUED)
            return True
        return False


    def _platform_task_id(self, job_id: str) -> str | None:
        row = self.store.get(job_id)
        if row is None:
            return None
        if row.platform_task_id:
            return row.platform_task_id
        try:
            payload = json.loads(row.payload_json or "{}")
        except json.JSONDecodeError:
            return None
        return payload.get("platform_task_id") or None

    def _notify_platform(self, job_id: str, *, fatal: bool = False) -> None:
        row = self.store.get(job_id)
        task_id = self._platform_task_id(job_id)
        if row is None or not task_id:
            return
        try:
            self.ingest_client.notify_task(
                task_id,
                status=row.status,
                error_code=row.error_code,
                error_message=row.error_message,
                data_ready_at=row.data_ready_at,
                processed_at=row.processed_at,
            )
        except Exception:
            if fatal:
                raise
            # 运行中进度回传失败不中断处理链

    def _log_stage(self, job_id: str, stage: str, started: datetime, **extra: Any) -> None:
        ended = utcnow()
        elapsed = (ended - started).total_seconds()
        budget = INTERNAL_BUDGET_MINUTES.get(stage)
        self.store.append_stage_log(
            job_id,
            {
                "stage": stage,
                "started_at": started.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "ended_at": ended.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "elapsed_seconds": elapsed,
                "internal_budget_minutes": budget,
                **extra,
            },
        )

    def _build_context(self, row: JobRow) -> PluginContext:
        payload = json.loads(row.payload_json or "{}")
        scene_data = dict(payload.get("scene") or {})
        scene_data.setdefault("scene_id", row.scene_id)
        if getattr(row, "s1_product_id", ""):
            scene_data.setdefault("s1_product_id", row.s1_product_id)
        scene = SceneMeta.model_validate(scene_data)
        if not scene.data_ready_at and row.data_ready_at:
            scene = scene.model_copy(update={"data_ready_at": row.data_ready_at})
        pilot_data = dict(payload.get("pilot") or payload.get("area") or {})
        area_id = payload.get("area_id") or getattr(row, "area_id", "") or row.pilot_id
        if area_id:
            pilot_data.setdefault("area_id", area_id)
        if "is_pilot" not in pilot_data and payload.get("is_pilot") is not None:
            pilot_data["is_pilot"] = payload.get("is_pilot")
        pilot = PilotConfig.model_validate(pilot_data)
        profile = load_default_profile()
        if row.algo_profile_id and row.algo_profile_id != profile.algo_profile_id:
            profile = profile.model_copy(update={"algo_profile_id": row.algo_profile_id})
        overrides = payload.get("param_overrides") or payload.get("overrides") or pilot.overrides
        profile = profile.apply_overrides(overrides)
        work = Path(row.work_dir) if row.work_dir else (self.settings.resolved_work_dir() / row.id)
        work.mkdir(parents=True, exist_ok=True)
        extras = dict(payload.get("extras") or {})
        if payload.get("use_synthetic_baseline"):
            extras["use_synthetic_baseline"] = True
        return PluginContext(
            job_id=row.id,
            work_dir=work,
            scene=scene,
            pilot=pilot,
            profile=profile,
            execution_mode=row.execution_mode,
            baseline_uri=payload.get("baseline_uri"),
            baseline_version_id=row.baseline_version_id or payload.get("baseline_version_id"),
            baseline_asset_id=payload.get("baseline_asset_id"),
            baseline_type=payload.get("baseline_type"),
            extras=extras,
        )

    def _run_pipeline(self, job_id: str) -> JobRow:
        t0 = utcnow()
        try:
            if self._cancel_if_requested(job_id):
                return self.store.get(job_id)
            row = self.store.get(job_id)
            if row.status != JobStatus.PREPARING:
                # 从断点恢复：直接进入记录的状态
                pass
            else:
                if self.step_hook:
                    self.step_hook(row, JobStatus.PREPARING)
                context = self._build_context(row)
                if not row.work_dir:
                    self.store.update(job_id, work_dir=str(context.work_dir))
                self._log_stage(job_id, "prepare", t0, budget_name="prepare")
                if self._maybe_preempt(job_id, JobStatus.PREPARING):
                    return self.store.get(job_id)

            row = self.store.get(job_id)
            context = self._build_context(row)
            plugin = self.registry.create(row.execution_mode)
            # plugin 的 gpt 路径可在构造时注入
            if row.execution_mode == ExecutionMode.SNAP.value and hasattr(plugin, "gpt_binary"):
                plugin.gpt_binary = self.settings.gpt_binary  # type: ignore[attr-defined]
                plugin.timeout = self.settings.gpt_timeout_seconds  # type: ignore[attr-defined]

            # snap_running
            self.store.transition(job_id, JobStatus.SNAP_RUNNING)
            self._notify_platform(job_id)
            if self._cancel_if_requested(job_id):
                return self.store.get(job_id)
            t_snap = utcnow()
            if self.step_hook:
                self.step_hook(self.store.get(job_id), JobStatus.SNAP_RUNNING)
            plugin.validate(context)
            result = plugin.run(context)
            self._log_stage(job_id, "snap_extract", t_snap, note="preprocess+后续提取同预算")
            # gpt 已结束，步骤边界允许抢占
            if self._maybe_preempt(job_id, JobStatus.SNAP_RUNNING, gpt_running=False):
                return self.store.get(job_id)

            # 后处理在内存中一次做完，但按状态机逐步打点，便于测试插队
            self.store.transition(job_id, JobStatus.EXTRACTING)
            self._notify_platform(job_id)
            if self._cancel_if_requested(job_id) or self._maybe_preempt(job_id, JobStatus.EXTRACTING):
                return self.store.get(job_id)
            if self.step_hook:
                self.step_hook(self.store.get(job_id), JobStatus.EXTRACTING)

            min_cov = context.profile.extract.min_valid_coverage_ratio
            if min_cov is None:
                min_cov = self.settings.min_valid_coverage_ratio

            t_area = utcnow()
            manifest, _parts = run_postprocess(
                context,
                result.preprocess,
                submitted_at=row.submitted_at,
                data_ready_at=row.data_ready_at,
                min_valid_coverage_ratio=float(min_cov),
            )

            for st in (JobStatus.CHANGE_DETECTING, JobStatus.IMPACT_MAPPING, JobStatus.QC):
                self.store.transition(job_id, st)
                if self.step_hook:
                    self.step_hook(self.store.get(job_id), st)
                if self._cancel_if_requested(job_id) or self._maybe_preempt(job_id, st):
                    return self.store.get(job_id)

            self.store.transition(job_id, JobStatus.INGESTING)
            self._notify_platform(job_id)
            if self.step_hook:
                self.step_hook(self.store.get(job_id), JobStatus.INGESTING)
            task_id = self._platform_task_id(job_id)
            title = None
            if context.pilot and context.pilot.name:
                status = manifest.metadata.flood_event_status if manifest.metadata else ""
                if status == "baseline_missing":
                    title = f"{context.pilot.name}提取水体范围（Sentinel-1）"
                else:
                    title = f"{context.pilot.name}洪水淹没范围（Sentinel-1）"
            ingest_resp = self.ingest_client.ingest(job_id, manifest, task_id=task_id, title=title)
            self._log_stage(job_id, "area_ingest", t_area)
            product_blob = json.loads(manifest.model_dump_json())
            product_blob["ingest"] = ingest_resp
            now = utcnow()
            row = self.store.transition(
                job_id,
                JobStatus.SUCCEEDED,
                product_id=manifest.product_id,
                result_json=json.dumps({"product": product_blob}, ensure_ascii=False, default=str),
                processed_at=now,
                finished_at=now,
                error_code=None,
                error_message=None,
            )
            self._notify_platform(job_id, fatal=True)
            return row
        except (EngineError, Exception) as exc:
            if not isinstance(exc, EngineError):
                tb = traceback.format_exc()
                exc = EngineError(ErrorCode.INTERNAL, f"{exc}\n{tb[-500:]}", retryable=True)
            # 若仍在 snap_running，保留可重试语义
            return self._fail_or_retry(job_id, exc)
