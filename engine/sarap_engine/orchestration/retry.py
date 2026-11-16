"""重试策略。

瞬时错误（gpt 崩溃、超时、磁盘、入库 5xx）：指数退避，默认最多 3 次。
SNAP 崩溃：先立即重试 1 次，仍失败再进入上述通用重试（合计最多 1+3 次额外尝试）。
业务错误（输入缺失、无 VV、参数非法、网格不对齐、pie_sar 未实现、有效覆盖过低）：不重试，直接 failed。
"""

from __future__ import annotations

from dataclasses import dataclass

from sarap_engine.constants import (
    BUSINESS_ERROR_CODES,
    TRANSIENT_ERROR_CODES,
    ErrorCode,
)


@dataclass(frozen=True)
class RetryDecision:
    retry: bool
    reason: str
    delay_seconds: float
    kind: str  # none / snap_immediate / general


def backoff_seconds(attempt: int, base: float = 2.0, max_wait: float = 60.0) -> float:
    """attempt 从 1 起。"""
    if attempt <= 0:
        attempt = 1
    return min(max_wait, float(base) ** attempt)


def is_transient(code: ErrorCode | str) -> bool:
    try:
        return ErrorCode(code) in TRANSIENT_ERROR_CODES
    except ValueError:
        return False


def is_business(code: ErrorCode | str) -> bool:
    try:
        return ErrorCode(code) in BUSINESS_ERROR_CODES
    except ValueError:
        return False


def decide_retry(
    code: ErrorCode | str,
    *,
    general_retry_count: int,
    snap_crash_retry_count: int,
    max_retries: int = 3,
    snap_immediate_retries: int = 1,
    retry_base_seconds: float = 2.0,
    retry_max_seconds: float = 60.0,
    retryable_override: bool | None = None,
) -> RetryDecision:
    err = ErrorCode(code) if code in ErrorCode._value2member_map_ or code in ErrorCode else ErrorCode.INTERNAL
    try:
        err = ErrorCode(code)
    except ValueError:
        err = ErrorCode.INTERNAL

    if retryable_override is False or is_business(err):
        return RetryDecision(False, "业务错误，不重试", 0.0, "none")

    retryable = is_transient(err) if retryable_override is None else retryable_override
    if not retryable:
        return RetryDecision(False, "不可重试错误", 0.0, "none")

    # SNAP 崩溃：先立即重试 1 次
    if err == ErrorCode.GPT_CRASH and snap_crash_retry_count < snap_immediate_retries:
        return RetryDecision(True, "SNAP 崩溃，先立即重试 1 次", 0.0, "snap_immediate")

    if general_retry_count >= max_retries:
        return RetryDecision(
            False,
            f"已达通用重试上限 {max_retries} 次",
            0.0,
            "none",
        )
    delay = backoff_seconds(
        general_retry_count + 1,
        base=retry_base_seconds,
        max_wait=retry_max_seconds,
    )
    return RetryDecision(True, "瞬时错误，指数退避后通用重试", delay, "general")
