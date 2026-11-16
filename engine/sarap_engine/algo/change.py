"""变化检测口径。有本底：flood_event = 当期确定水 AND NOT 有效本底。

无本底：class_map 用 5=extracted_water，不写 2/3，不把本次淹没标成可自动发布。
本底 nodata 不得算本次淹没。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from sarap_engine.algo.grid import GridSpec, assert_grids_aligned
from sarap_engine.constants import ClassCode, FloodEventStatus, qc_bit, QcFlag


# 本底约定：0=非水/nodata 需靠 baseline_valid 区分；推荐 0 非水、1 水体，有效区外为 nodata。
BASELINE_WATER = 1


@dataclass
class ChangeResult:
    class_map: np.ndarray
    water_current: np.ndarray  # 0/1 当期确定水体
    flood_event: np.ndarray  # 0/1；无本底时全 0
    qc_flags: np.ndarray
    has_baseline: bool
    flood_event_status: str


def classify_without_baseline(
    hard_water: np.ndarray,
    lowconf: np.ndarray,
    nodata: np.ndarray,
    qc_flags: np.ndarray,
) -> ChangeResult:
    """P0 无本底：确定水体写 5，不得写 2/3。"""
    cm = np.full(hard_water.shape, ClassCode.NON_WATER, dtype=np.uint8)
    cm[np.asarray(nodata, dtype=bool)] = ClassCode.NODATA
    cm[np.asarray(lowconf, dtype=bool)] = ClassCode.WATER_LOWCONF
    cm[np.asarray(hard_water, dtype=bool)] = ClassCode.EXTRACTED_WATER
    water_current = (cm == ClassCode.EXTRACTED_WATER).astype(np.uint8)
    flood = np.zeros(cm.shape, dtype=np.uint8)
    return ChangeResult(
        class_map=cm,
        water_current=water_current,
        flood_event=flood,
        qc_flags=qc_flags,
        has_baseline=False,
        flood_event_status=FloodEventStatus.BASELINE_MISSING.value,
    )


def classify_with_baseline(
    hard_water: np.ndarray,
    lowconf: np.ndarray,
    nodata: np.ndarray,
    qc_flags: np.ndarray,
    baseline_water: np.ndarray,
    baseline_valid: np.ndarray,
    *,
    current_grid: GridSpec | None = None,
    baseline_grid: GridSpec | None = None,
) -> ChangeResult:
    """
    官方口径：
      water_current_hard = 确定水体（即将写入 2 或 3，不含 4）
      flood_event        = water_current_hard AND NOT water_baseline_effective
    本底 nodata：当期即使提水，也只能进 water_lowconf 或标记 baseline_gap，不得算本次淹没。
    有本底时 class_map 写 2/3，不必写 5。
    """
    if current_grid is not None and baseline_grid is not None:
        # 同窗口对比要求形状与原点一致
        assert_grids_aligned(current_grid, baseline_grid, require_same_shape=True)

    hard = np.asarray(hard_water, dtype=bool).copy()
    low = np.asarray(lowconf, dtype=bool).copy()
    invalid = np.asarray(nodata, dtype=bool)
    flags = np.asarray(qc_flags, dtype=np.uint16).copy()
    bwater = np.asarray(baseline_water, dtype=bool)
    bvalid = np.asarray(baseline_valid, dtype=bool)

    # 本底缺测且当期确定水 → 不得算本次淹没，降为低置信并打 BASELINE_GAP
    gap = hard & ~bvalid
    if gap.any():
        flags[gap] = flags[gap] | np.uint16(qc_bit(QcFlag.BASELINE_GAP))
        hard[gap] = False
        low[gap] = True
    # 本底缺测本身也打 flag（即使当期非水），便于质控摘要
    flags[~bvalid & ~invalid] = flags[~bvalid & ~invalid] | np.uint16(qc_bit(QcFlag.BASELINE_GAP))

    flood = hard & bvalid & ~bwater
    baseline_curr = hard & bvalid & bwater

    cm = np.full(hard.shape, ClassCode.NON_WATER, dtype=np.uint8)
    cm[invalid] = ClassCode.NODATA
    cm[low] = ClassCode.WATER_LOWCONF
    cm[baseline_curr] = ClassCode.PERMANENT_OR_BASELINE_WATER
    cm[flood] = ClassCode.FLOOD_EVENT
    # 有本底时不写 5
    water_current = np.isin(cm, [ClassCode.PERMANENT_OR_BASELINE_WATER, ClassCode.FLOOD_EVENT]).astype(np.uint8)
    return ChangeResult(
        class_map=cm,
        water_current=water_current,
        flood_event=flood.astype(np.uint8),
        qc_flags=flags,
        has_baseline=True,
        flood_event_status=FloodEventStatus.COMPUTED.value,
    )
