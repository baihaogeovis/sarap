"""任务状态存储，默认 SQLite。"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from sarap_engine.constants import JobStatus, Priority
from sarap_engine.orchestration.models import Base, JobRow, utcnow
from sarap_engine.orchestration.state_machine import transition as sm_transition


def _ensure_aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


class JobStore:
    def __init__(self, db_url: str = "sqlite:///:memory:") -> None:
        connect_args: dict[str, Any] = {}
        engine_kwargs: dict[str, Any] = {"future": True}
        if db_url.startswith("sqlite"):
            connect_args["check_same_thread"] = False
            # :memory: 每个连接都是独立空库；StaticPool 保证建表与读写共用同一连接
            if ":memory:" in db_url or db_url in {"sqlite://", "sqlite:///", "sqlite:///:memory:"}:
                engine_kwargs["poolclass"] = StaticPool
        engine_kwargs["connect_args"] = connect_args
        self.engine = create_engine(db_url, **engine_kwargs)
        Base.metadata.create_all(self.engine)
        self._ensure_columns()
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False, future=True)
        self._seq = 0

    def _ensure_columns(self) -> None:
        if self.engine.dialect.name != "sqlite":
            return
        with self.engine.connect() as conn:
            rows = conn.exec_driver_sql("PRAGMA table_info(engine_jobs)").fetchall()
            cols = {row[1] for row in rows}
            alters = []
            if "platform_task_id" not in cols:
                alters.append("ALTER TABLE engine_jobs ADD COLUMN platform_task_id VARCHAR(36) DEFAULT ''")
            if "area_id" not in cols:
                alters.append("ALTER TABLE engine_jobs ADD COLUMN area_id VARCHAR(128) DEFAULT ''")
            if "s1_product_id" not in cols:
                alters.append("ALTER TABLE engine_jobs ADD COLUMN s1_product_id VARCHAR(256) DEFAULT ''")
            for sql in alters:
                conn.exec_driver_sql(sql)
            if alters:
                conn.commit()

    def session(self) -> Session:
        return self.Session()

    def _next_seq(self, s: Session) -> int:
        val = s.scalar(select(func.max(JobRow.queue_seq)))
        return int(val or 0) + 1

    def add(self, row: JobRow) -> JobRow:
        with self.session() as s:
            if not row.queue_seq:
                row.queue_seq = self._next_seq(s)
            s.add(row)
            s.commit()
            s.refresh(row)
            return row

    def get(self, job_id: str) -> JobRow | None:
        with self.session() as s:
            return s.get(JobRow, job_id)

    def find_by_idempotency(self, key: str) -> JobRow | None:
        with self.session() as s:
            stmt = (
                select(JobRow)
                .where(JobRow.idempotency_key == key)
                .order_by(JobRow.submitted_at.desc())
            )
            return s.scalars(stmt).first()

    def list_jobs(self, *, status: str | None = None, limit: int = 100) -> list[JobRow]:
        with self.session() as s:
            stmt = select(JobRow).order_by(JobRow.submitted_at.desc()).limit(limit)
            if status:
                stmt = (
                    select(JobRow)
                    .where(JobRow.status == status)
                    .order_by(JobRow.submitted_at.desc())
                    .limit(limit)
                )
            return list(s.scalars(stmt).all())

    def update(self, job_id: str, **fields: Any) -> JobRow:
        with self.session() as s:
            row = s.get(JobRow, job_id)
            if row is None:
                raise KeyError(job_id)
            fields["updated_at"] = utcnow()
            for k, v in fields.items():
                setattr(row, k, v)
            s.commit()
            s.refresh(row)
            return row

    def transition(self, job_id: str, dest: JobStatus | str, **fields: Any) -> JobRow:
        with self.session() as s:
            row = s.get(JobRow, job_id)
            if row is None:
                raise KeyError(job_id)
            new_status = sm_transition(row.status, dest)
            row.status = new_status.value
            fields["updated_at"] = utcnow()
            for k, v in fields.items():
                setattr(row, k, v)
            s.commit()
            s.refresh(row)
            return row

    def set_json(self, job_id: str, field: str, value: Any) -> JobRow:
        return self.update(job_id, **{field: json.dumps(value, ensure_ascii=False, default=str)})

    def append_stage_log(self, job_id: str, entry: dict[str, Any]) -> None:
        with self.session() as s:
            row = s.get(JobRow, job_id)
            if row is None:
                raise KeyError(job_id)
            try:
                log = json.loads(row.stage_log_json or "[]")
            except json.JSONDecodeError:
                log = []
            log.append(entry)
            row.stage_log_json = json.dumps(log, ensure_ascii=False, default=str)
            row.updated_at = utcnow()
            s.commit()

    def has_queued_emergency(self, exclude_id: str | None = None) -> bool:
        with self.session() as s:
            stmt = select(func.count()).select_from(JobRow).where(
                JobRow.status == JobStatus.QUEUED.value,
                JobRow.priority == Priority.EMERGENCY.value,
            )
            if exclude_id:
                stmt = stmt.where(JobRow.id != exclude_id)
            return int(s.scalar(stmt) or 0) > 0

    def due_retry_jobs(self, now: datetime | None = None) -> list[JobRow]:
        now = _ensure_aware(now) or utcnow()
        with self.session() as s:
            stmt = select(JobRow).where(JobRow.status == JobStatus.RETRY_WAIT.value)
            rows = list(s.scalars(stmt).all())
        ready = []
        for r in rows:
            retry_at = _ensure_aware(r.retry_at)
            if retry_at is None or retry_at <= now:
                ready.append(r)
        return ready

    def close(self) -> None:
        self.engine.dispose()
