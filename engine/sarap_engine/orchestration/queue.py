"""优先级队列：emergency 始终排在 normal 之前；同级按提交顺序 FIFO。"""

from __future__ import annotations

from sqlalchemy import select

from sarap_engine.constants import JobStatus, Priority
from sarap_engine.orchestration.models import JobRow
from sarap_engine.orchestration.state_machine import JobStatus as _JS  # noqa: F401
from sarap_engine.orchestration.store import JobStore


class JobQueue:
    def __init__(self, store: JobStore) -> None:
        self.store = store

    def promote_due_retries(self) -> int:
        n = 0
        for row in self.store.due_retry_jobs():
            self.store.transition(row.id, JobStatus.QUEUED)
            n += 1
        return n

    def pop_next(self) -> JobRow | None:
        """取出下一个应执行的 queued 任务（emergency 优先）。"""
        self.promote_due_retries()
        with self.store.session() as s:
            # 优先级：emergency 在前，然后 queue_seq 升序
            emergency = list(
                s.scalars(
                    select(JobRow)
                    .where(
                        JobRow.status == JobStatus.QUEUED.value,
                        JobRow.priority == Priority.EMERGENCY.value,
                    )
                    .order_by(JobRow.queue_seq.asc())
                    .limit(1)
                ).all()
            )
            if emergency:
                row = emergency[0]
            else:
                row = s.scalars(
                    select(JobRow)
                    .where(JobRow.status == JobStatus.QUEUED.value)
                    .order_by(JobRow.queue_seq.asc())
                    .limit(1)
                ).first()
            if row is None:
                return None
            job_id = row.id
        # 从 queued → preparing 在 worker 中完成，这里只返回
        return self.store.get(job_id)

    def peek_order(self) -> list[str]:
        """返回当前排队顺序（仅测试/诊断）。"""
        self.promote_due_retries()
        with self.store.session() as s:
            rows = list(
                s.scalars(
                    select(JobRow)
                    .where(JobRow.status == JobStatus.QUEUED.value)
                    .order_by(
                        # emergency first: map to 0/1
                        (JobRow.priority != Priority.EMERGENCY.value),
                        JobRow.queue_seq.asc(),
                    )
                ).all()
            )
        return [r.id for r in rows]
