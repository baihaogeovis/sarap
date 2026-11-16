"""质控：建成区降级、阴影/叠掩/入射角/边缘等 flag。一般警告不阻断 P0 发布。"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from sarap_engine.algo.morphology import binary_dilation
from sarap_engine.constants import QcFlag, UrbanPolicy, qc_bit


@dataclass
class QcDowngradeResult:
    hard_water: np.ndarray
    lowconf: np.ndarray
    nodata: np.ndarray
    qc_flags: np.ndarray


def apply_risk_downgrade(
    hard_water: np.ndarray,
    lowconf: np.ndarray,
    *,
    qc_flags: np.ndarray,
    nodata: np.ndarray,
    urban: np.ndarray | None = None,
    urban_policy: UrbanPolicy | str = UrbanPolicy.DOWNGRADE,
    shadow: np.ndarray | None = None,
    slope: np.ndarray | None = None,
    slope_deg: float = 15.0,
    layover: np.ndarray | None = None,
    mark_edge: bool = True,
) -> QcDowngradeResult:
    """
    建成区默认降为 lowconf，而不是删除或直接算确定淹没。
    阴影/陡坡：候选水体降为低置信。
    叠掩：强制 nodata/非水（若尚未在提取阶段排除）。
    禁止把建成区全部掩成非水且不留痕迹。
    """
    hard = np.asarray(hard_water, dtype=bool).copy()
    low = np.asarray(lowconf, dtype=bool).copy()
    flags = np.asarray(qc_flags, dtype=np.uint16).copy()
    invalid = np.asarray(nodata, dtype=bool).copy()
    policy = UrbanPolicy(urban_policy)

    if layover is not None:
        lay = np.asarray(layover, dtype=bool)
        flags[lay] = flags[lay] | np.uint16(qc_bit(QcFlag.LAYOVER))
        hard[lay] = False
        low[lay] = False
        invalid[lay] = True

    shadow_mask = np.zeros(hard.shape, dtype=bool)
    if shadow is not None:
        shadow_mask |= np.asarray(shadow, dtype=bool)
    if slope is not None:
        sl = np.asarray(slope, dtype=np.float64)
        shadow_mask |= np.isfinite(sl) & (sl > slope_deg)
    if shadow_mask.any():
        flags[shadow_mask] = flags[shadow_mask] | np.uint16(qc_bit(QcFlag.SHADOW))
        # 阴影中的候选确定水降为低置信
        to_low = hard & shadow_mask
        hard[to_low] = False
        low[to_low] = True

    if urban is not None:
        urb = np.asarray(urban, dtype=bool)
        flags[urb] = flags[urb] | np.uint16(qc_bit(QcFlag.URBAN))
        if policy == UrbanPolicy.DOWNGRADE:
            to_low = hard & urb
            hard[to_low] = False
            low[to_low] = True
        # keep_with_flag：保留确定水但必须出旗标（已写 URBAN）
        # 禁止第三种：直接掩成非水

    if mark_edge:
        water = hard | low
        edge = binary_dilation(water, size=3) & ~water & ~invalid
        flags[edge] = flags[edge] | np.uint16(qc_bit(QcFlag.EDGE_MIXED))

    # 无效区不应残留分类
    hard[invalid] = False
    low[invalid] = False
    # 低置信与确定水互斥
    low[hard] = False
    return QcDowngradeResult(hard_water=hard, lowconf=low, nodata=invalid, qc_flags=flags)


def flag_area_ha(flags: np.ndarray, bit: int, res_m: float) -> float:
    mask = (np.asarray(flags, dtype=np.uint16) & np.uint16(1 << bit)) != 0
    return round(int(mask.sum()) * res_m * res_m / 10000.0, 2)
