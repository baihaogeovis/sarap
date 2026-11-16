"""任务状态与合法迁移。

引擎任务状态（合并原方案与规范 13.1，review/published 属平台生命周期，引擎不发布）：
  accepted → queued → preparing → snap_running → extracting
  → change_detecting → impact_mapping → qc → ingesting → succeeded
以及 retry_wait、failed、cancelled、preempted。
preempted 在步骤边界让出后回到 queued，优先级低于 emergency。
"""

from __future__ import annotations

from sarap_engine.constants import JobStatus

# 合法迁移表
TRANSITIONS: dict[JobStatus, frozenset[JobStatus]] = {
    JobStatus.ACCEPTED: frozenset({JobStatus.QUEUED, JobStatus.CANCELLED, JobStatus.FAILED}),
    JobStatus.QUEUED: frozenset(
        {JobStatus.PREPARING, JobStatus.CANCELLED, JobStatus.FAILED}
    ),
    JobStatus.PREPARING: frozenset(
        {
            JobStatus.SNAP_RUNNING,
            JobStatus.PREEMPTED,
            JobStatus.FAILED,
            JobStatus.CANCELLED,
            JobStatus.RETRY_WAIT,
        }
    ),
    JobStatus.SNAP_RUNNING: frozenset(
        {
            JobStatus.EXTRACTING,
            JobStatus.FAILED,
            JobStatus.RETRY_WAIT,
            JobStatus.CANCELLED,  # gpt 已结束后在边界响应取消，不 SIGKILL
        }
    ),
    JobStatus.EXTRACTING: frozenset(
        {
            JobStatus.CHANGE_DETECTING,
            JobStatus.PREEMPTED,
            JobStatus.FAILED,
            JobStatus.CANCELLED,
            JobStatus.RETRY_WAIT,
        }
    ),
    JobStatus.CHANGE_DETECTING: frozenset(
        {
            JobStatus.IMPACT_MAPPING,
            JobStatus.PREEMPTED,
            JobStatus.FAILED,
            JobStatus.CANCELLED,
            JobStatus.RETRY_WAIT,
        }
    ),
    JobStatus.IMPACT_MAPPING: frozenset(
        {
            JobStatus.QC,
            JobStatus.PREEMPTED,
            JobStatus.FAILED,
            JobStatus.CANCELLED,
            JobStatus.RETRY_WAIT,
        }
    ),
    JobStatus.QC: frozenset(
        {
            JobStatus.INGESTING,
            JobStatus.PREEMPTED,
            JobStatus.FAILED,
            JobStatus.CANCELLED,
            JobStatus.RETRY_WAIT,
        }
    ),
    JobStatus.INGESTING: frozenset(
        {
            JobStatus.SUCCEEDED,
            JobStatus.PREEMPTED,
            JobStatus.FAILED,
            JobStatus.CANCELLED,
            JobStatus.RETRY_WAIT,
        }
    ),
    JobStatus.RETRY_WAIT: frozenset({JobStatus.QUEUED, JobStatus.CANCELLED, JobStatus.FAILED}),
    JobStatus.PREEMPTED: frozenset({JobStatus.QUEUED, JobStatus.CANCELLED, JobStatus.FAILED}),
    JobStatus.SUCCEEDED: frozenset(),
    JobStatus.FAILED: frozenset(),
    JobStatus.CANCELLED: frozenset(),
}

TERMINAL = frozenset({JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED})

# 这些状态完成之后（即将进入下一状态前）可以让出给应急任务
PREEMPTIBLE_AFTER = frozenset(
    {
        JobStatus.PREPARING,
        JobStatus.SNAP_RUNNING,  # 仅在 gpt 完成之后检查
        JobStatus.EXTRACTING,
        JobStatus.CHANGE_DETECTING,
        JobStatus.IMPACT_MAPPING,
        JobStatus.QC,
    }
)

# worker 执行中的步骤状态
STEP_STATUSES = (
    JobStatus.PREPARING,
    JobStatus.SNAP_RUNNING,
    JobStatus.EXTRACTING,
    JobStatus.CHANGE_DETECTING,
    JobStatus.IMPACT_MAPPING,
    JobStatus.QC,
    JobStatus.INGESTING,
)


class IllegalTransition(ValueError):
    def __init__(self, src: JobStatus, dst: JobStatus) -> None:
        self.src = src
        self.dst = dst
        super().__init__(f"非法状态迁移: {src} → {dst}")


def can_transition(src: JobStatus | str, dst: JobStatus | str) -> bool:
    s, d = JobStatus(src), JobStatus(dst)
    return d in TRANSITIONS.get(s, frozenset())


def transition(src: JobStatus | str, dst: JobStatus | str) -> JobStatus:
    s, d = JobStatus(src), JobStatus(dst)
    if d not in TRANSITIONS.get(s, frozenset()):
        raise IllegalTransition(s, d)
    return d


def is_terminal(status: JobStatus | str) -> bool:
    return JobStatus(status) in TERMINAL
