"""应急插队：只在步骤边界让出，不杀死正在跑的 gpt。"""

from __future__ import annotations

from sarap_engine.constants import JobStatus, Priority
from sarap_engine.orchestration.state_machine import PREEMPTIBLE_AFTER


def should_preempt(
    current_priority: Priority | str,
    current_status: JobStatus | str,
    *,
    emergency_waiting: bool,
    gpt_running: bool = False,
) -> bool:
    """
    普通任务在步骤边界若有应急任务等待，则标 preempted 并带检查点回到 queued。
    不在 snap_running 期间（gpt 仍在跑）抢占。
    """
    if not emergency_waiting:
        return False
    if Priority(current_priority) == Priority.EMERGENCY:
        return False
    if gpt_running or JobStatus(current_status) == JobStatus.SNAP_RUNNING:
        # 仅在 snap_running *完成之后* 才检查；函数由调用方在边界处使用
        # 若仍处于 snap_running 且 gpt 未结束，返回 False
        if gpt_running:
            return False
        # snap 已完成、正要离开 snap_running 时允许
        return JobStatus(current_status) in PREEMPTIBLE_AFTER
    return JobStatus(current_status) in PREEMPTIBLE_AFTER
