"""面积统计：以与 class_map 一致的栅格像元计数为准。"""

from __future__ import annotations

from typing import Any

import numpy as np

from sarap_engine.constants import (
    AREA_LIMITATION,
    EXTRACTED_WATER_AREA_LABEL,
    FLOOD_EVENT_AREA_LABEL,
    WATER_CURRENT_AREA_LABEL,
    ClassCode,
    FloodEventStatus,
)


def pixel_area_m2(res_m: float) -> float:
    return float(res_m) * float(res_m)


def count_to_m2(count: int, res_m: float) -> int:
    return int(round(count * pixel_area_m2(res_m)))


def count_to_ha(count: int, res_m: float) -> float:
    return round(count * pixel_area_m2(res_m) / 10000.0, 2)


def area_stats(
    class_map: np.ndarray,
    *,
    res_m: float,
    has_baseline: bool,
    lowconf_in_official: bool = False,
) -> dict[str, Any]:
    """P0 面积。无本底用 extracted_water_ha 及「未扣本底」文案；有本底同时给当期和本次淹没。"""
    cm = np.asarray(class_map)
    n_low = int((cm == ClassCode.WATER_LOWCONF).sum())
    metrics: list[dict[str, Any]] = []
    extracted = int((cm == ClassCode.EXTRACTED_WATER).sum())
    current = int(np.isin(cm, [ClassCode.PERMANENT_OR_BASELINE_WATER, ClassCode.FLOOD_EVENT, ClassCode.EXTRACTED_WATER]).sum())
    flood = int((cm == ClassCode.FLOOD_EVENT).sum())

    if has_baseline:
        metrics.append(
            {
                "metric": "water_current_ha",
                "value": count_to_ha(current, res_m),
                "unit": "ha",
                "label": WATER_CURRENT_AREA_LABEL,
                "scope": "default",
            }
        )
        metrics.append(
            {
                "metric": "water_current_m2",
                "value": count_to_m2(current, res_m),
                "unit": "m2",
                "label": WATER_CURRENT_AREA_LABEL,
                "scope": "default",
            }
        )
        metrics.append(
            {
                "metric": "flood_event_ha",
                "value": count_to_ha(flood, res_m),
                "unit": "ha",
                "label": FLOOD_EVENT_AREA_LABEL,
                "scope": "default",
            }
        )
        metrics.append(
            {
                "metric": "flood_event_m2",
                "value": count_to_m2(flood, res_m),
                "unit": "m2",
                "label": FLOOD_EVENT_AREA_LABEL,
                "scope": "default",
            }
        )
        flood_event_status = FloodEventStatus.COMPUTED.value
        official_note = "本次淹没 = 当期确定水体 − 有效本底；低置信默认不计入对外面积。"
    else:
        metrics.append(
            {
                "metric": "extracted_water_ha",
                "value": count_to_ha(extracted, res_m),
                "unit": "ha",
                "label": EXTRACTED_WATER_AREA_LABEL,
                "scope": "default",
            }
        )
        metrics.append(
            {
                "metric": "extracted_water_m2",
                "value": count_to_m2(extracted, res_m),
                "unit": "m2",
                "label": EXTRACTED_WATER_AREA_LABEL,
                "scope": "default",
            }
        )
        flood_event_status = FloodEventStatus.BASELINE_MISSING.value
        official_note = "提取水体面积（未扣本底）。不得将此值称为本次淹没。"

    # 附录：含低置信
    if lowconf_in_official or True:
        if has_baseline:
            incl = current + n_low
            metrics.append(
                {
                    "metric": "water_current_ha",
                    "value": count_to_ha(incl, res_m),
                    "unit": "ha",
                    "label": "当期水体面积（含低置信）",
                    "scope": "including_lowconf",
                }
            )
        else:
            incl = extracted + n_low
            metrics.append(
                {
                    "metric": "extracted_water_ha",
                    "value": count_to_ha(incl, res_m),
                    "unit": "ha",
                    "label": "提取水体面积（未扣本底，含低置信）",
                    "scope": "including_lowconf",
                }
            )

    return {
        "metrics": metrics,
        "limitation": AREA_LIMITATION,
        "official_note": official_note,
        "flood_event_status": flood_event_status,
        "counts": {
            "extracted_water": extracted,
            "water_current_hard": current,
            "flood_event": flood,
            "water_lowconf": n_low,
        },
        "extracted_water_ha": count_to_ha(extracted, res_m) if not has_baseline else None,
        "water_current_ha": count_to_ha(current, res_m) if has_baseline else count_to_ha(current, res_m),
        "flood_event_ha": count_to_ha(flood, res_m) if has_baseline else None,
        "lowconf_ha": count_to_ha(n_low, res_m),
    }
