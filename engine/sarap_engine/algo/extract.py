"""水体提取：VV 主规则、VH 约束、形态学、MMU。纯 numpy。"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from sarap_engine.algo.morphology import (
    binary_closing,
    binary_opening,
    remove_small_components,
    restore_adjacent_small,
)
from sarap_engine.algo.threshold import ThresholdResult, estimate_threshold
from sarap_engine.constants import QcFlag, qc_bit


@dataclass
class ExtractResult:
    candidate: np.ndarray  # 候选水体（含将被降为低置信的像元）
    hard_water: np.ndarray  # 确定水体（尚未叠加建成区/阴影降级）
    lowconf: np.ndarray
    nodata: np.ndarray
    valid: np.ndarray
    mmu_removed: np.ndarray
    qc_flags: np.ndarray
    threshold: ThresholdResult
    extras: dict = field(default_factory=dict)


def mmu_pixels(mmu_ha: float, res_m: float) -> int:
    area_m2 = mmu_ha * 10000.0
    px = area_m2 / (res_m * res_m)
    return max(1, int(round(px)))


def valid_pixel_mask(
    vv_db: np.ndarray,
    *,
    incidence: np.ndarray | None = None,
    layover: np.ndarray | None = None,
    nodata: np.ndarray | None = None,
    incidence_range: tuple[float, float] = (30.0, 45.0),
    qc_flags: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """
    同时满足才进入提取：非 nodata、入射角在区间、不在叠掩内。
    超出入射角记 INCIDENCE，不进确定水体；叠掩记 LAYOVER。
    返回 (valid_for_extract, nodata_or_layover_mask)。
    """
    vv = np.asarray(vv_db, dtype=np.float64)
    shape = vv.shape
    if qc_flags is None:
        qc_flags = np.zeros(shape, dtype=np.uint16)
    invalid = nodata.copy() if nodata is not None else ~np.isfinite(vv)
    invalid |= ~np.isfinite(vv)

    if layover is not None:
        lay = np.asarray(layover, dtype=bool)
        qc_flags[lay] = qc_flags[lay] | np.uint16(qc_bit(QcFlag.LAYOVER))
        invalid |= lay

    inc_out = np.zeros(shape, dtype=bool)
    if incidence is not None:
        inc = np.asarray(incidence, dtype=np.float64)
        lo, hi = incidence_range
        known = np.isfinite(inc) & ~invalid
        inc_out = known & ((inc < lo) | (inc > hi))
        qc_flags[inc_out] = qc_flags[inc_out] | np.uint16(qc_bit(QcFlag.INCIDENCE))

    valid = ~invalid & ~inc_out
    return valid, invalid


def extract_water(
    vv_db: np.ndarray,
    *,
    vh_db: np.ndarray | None = None,
    incidence: np.ndarray | None = None,
    layover: np.ndarray | None = None,
    nodata: np.ndarray | None = None,
    urban: np.ndarray | None = None,
    slope: np.ndarray | None = None,
    t_default: float = -18.0,
    t_clamp: tuple[float, float] = (-23.0, -14.0),
    incidence_range: tuple[float, float] = (30.0, 45.0),
    slope_deg: float = 15.0,
    mmu_ha: float = 0.3,
    res_m: float = 10.0,
    morph_kernel_px: int = 3,
    use_vh_constraint: bool = True,
    t_vh_bright: float = -12.0,
    keep_adjacent_small_patches: bool = False,
    qc_flags: np.ndarray | None = None,
) -> ExtractResult:
    """
    主流程（质控降级如建成区/阴影在 qc.apply_risk_downgrade 中进行）：
    1. 有效像元；阈值估计排除建成区与陡坡。
    2. VV < T 为候选；VH 偏亮降为低置信。
    3. MMU → 闭运算 → 开运算 → 再 MMU。
    """
    vv = np.asarray(vv_db, dtype=np.float64)
    shape = vv.shape
    if qc_flags is None:
        qc_flags = np.zeros(shape, dtype=np.uint16)
    else:
        qc_flags = qc_flags.copy()

    valid, invalid = valid_pixel_mask(
        vv,
        incidence=incidence,
        layover=layover,
        nodata=nodata,
        incidence_range=incidence_range,
        qc_flags=qc_flags,
    )

    # 阈值估计不使用建成区、陡坡像元
    estimate_valid = valid.copy()
    if urban is not None:
        estimate_valid &= ~np.asarray(urban, dtype=bool)
    if slope is not None:
        sl = np.asarray(slope, dtype=np.float64)
        estimate_valid &= ~(np.isfinite(sl) & (sl > slope_deg))

    thr = estimate_threshold(
        vv,
        estimate_valid,
        t_default=t_default,
        t_clamp=t_clamp,
    )

    vv_cand = valid & (vv < thr.T)
    lowconf = np.zeros(shape, dtype=bool)
    if use_vh_constraint and vh_db is not None:
        vh = np.asarray(vh_db, dtype=np.float64)
        bright = vv_cand & np.isfinite(vh) & (vh > t_vh_bright)
        lowconf |= bright
        vv_cand = vv_cand & ~bright

    min_px = mmu_pixels(mmu_ha, res_m)
    # MMU 作用于全部候选（含将保留的确定水；已在 VH 中分出的低置信暂不参与 MMU 删除统计？
    # 规范：去除面积小于 MMU 的候选图斑。这里对确定候选做 MMU，低置信单独保留但也可去掉过小碎斑。
    hard = vv_cand
    hard, removed1 = remove_small_components(hard, min_px)
    if keep_adjacent_small_patches:
        hard, removed1 = restore_adjacent_small(hard, removed1)
    qc_flags[removed1] = qc_flags[removed1] | np.uint16(qc_bit(QcFlag.MMU_REMOVED))

    k = max(1, int(morph_kernel_px))
    if k >= 2:
        hard = binary_closing(hard, size=k)
        hard = binary_opening(hard, size=k)
        # 形态学可能侵入无效区，裁回有效像元
        hard &= valid

    hard, removed2 = remove_small_components(hard, min_px)
    qc_flags[removed2] = qc_flags[removed2] | np.uint16(qc_bit(QcFlag.MMU_REMOVED))
    mmu_removed = removed1 | removed2

    # 形态学后重新落入 hard 的像元不应再标低置信
    lowconf = lowconf & ~hard & valid
    candidate = hard | lowconf

    return ExtractResult(
        candidate=candidate,
        hard_water=hard,
        lowconf=lowconf,
        nodata=invalid,
        valid=valid,
        mmu_removed=mmu_removed,
        qc_flags=qc_flags,
        threshold=thr,
        extras={"mmu_pixels": min_px},
    )
