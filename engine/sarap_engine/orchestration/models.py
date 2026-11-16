"""任务记录（SQLAlchemy + 纯数据模型）。"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_job_id() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class JobRow(Base):
    __tablename__ = "engine_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    priority: Mapped[str] = mapped_column(String(16), index=True, default="normal")
    execution_mode: Mapped[str] = mapped_column(String(16), default="mock")
    idempotency_key: Mapped[str] = mapped_column(String(256), index=True)
    scene_id: Mapped[str] = mapped_column(String(128), index=True)
    area_id: Mapped[str] = mapped_column(String(128), default="", index=True)
    s1_product_id: Mapped[str] = mapped_column(String(256), default="")
    pilot_id: Mapped[str] = mapped_column(String(128), default="", index=True)
    baseline_version_id: Mapped[str] = mapped_column(String(128), default="")
    algo_profile_id: Mapped[str] = mapped_column(String(128), default="s1_grd_flood_v1")
    param_hash: Mapped[str] = mapped_column(String(64), default="")
    force_rerun: Mapped[bool] = mapped_column(Boolean, default=False)
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    result_json: Mapped[str] = mapped_column(Text, default="{}")
    checkpoint_json: Mapped[str] = mapped_column(Text, default="{}")
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    snap_crash_retry_count: Mapped[int] = mapped_column(Integer, default=0)
    retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    product_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    platform_task_id: Mapped[str] = mapped_column(String(36), default="", index=True)
    work_dir: Mapped[str | None] = mapped_column(Text, nullable=True)
    queue_seq: Mapped[int] = mapped_column(Integer, default=0)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    data_ready_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    stage_log_json: Mapped[str] = mapped_column(Text, default="[]")


def job_to_dict(row: JobRow) -> dict[str, Any]:
    import json

    def ts(v: datetime | None) -> str | None:
        if v is None:
            return None
        if v.tzinfo is None:
            v = v.replace(tzinfo=timezone.utc)
        return v.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    try:
        payload = json.loads(row.payload_json or "{}")
    except json.JSONDecodeError:
        payload = {}
    try:
        result = json.loads(row.result_json or "{}")
    except json.JSONDecodeError:
        result = {}
    try:
        checkpoint = json.loads(row.checkpoint_json or "{}")
    except json.JSONDecodeError:
        checkpoint = {}
    try:
        stage_log = json.loads(row.stage_log_json or "[]")
    except json.JSONDecodeError:
        stage_log = []

    return {
        "id": row.id,
        "status": row.status,
        "priority": row.priority,
        "execution_mode": row.execution_mode,
        "idempotency_key": row.idempotency_key,
        "scene_id": row.scene_id,
        "area_id": getattr(row, "area_id", "") or payload.get("area_id") or row.pilot_id,
        "s1_product_id": getattr(row, "s1_product_id", "") or payload.get("s1_product_id") or None,
        "pilot_id": row.pilot_id or None,
        "baseline_version_id": row.baseline_version_id or None,
        "algo_profile_id": row.algo_profile_id,
        "param_hash": row.param_hash,
        "force_rerun": row.force_rerun,
        "error_code": row.error_code,
        "error_message": row.error_message,
        "retry_count": row.retry_count,
        "snap_crash_retry_count": row.snap_crash_retry_count,
        "cancel_requested": row.cancel_requested,
        "product_id": row.product_id,
        "task_id": row.platform_task_id or None,
        "product": result.get("product") if isinstance(result, dict) else None,
        "result": result,
        "checkpoint": checkpoint,
        "payload": payload,
        "stage_log": stage_log,
        "data_ready_at": ts(row.data_ready_at),
        "submitted_at": ts(row.submitted_at),
        "started_at": ts(row.started_at),
        "processed_at": ts(row.processed_at),
        "finished_at": ts(row.finished_at),
        "updated_at": ts(row.updated_at),
        "reused": False,
    }
