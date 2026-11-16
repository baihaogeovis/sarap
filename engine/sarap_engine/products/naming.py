"""产品命名：SARAP_FLOOD_{pilot}_{S1_PID}_{acq}_{baseline}_{algo}_{prod_ver}。仅 ASCII 与下划线。"""

from __future__ import annotations

import re
from datetime import datetime, timezone

_SAFE = re.compile(r"[^A-Za-z0-9_]+")


def _tok(value: str | None, fallback: str = "NA") -> str:
    s = (value or fallback).strip() or fallback
    s = s.replace("-", "_").replace(":", "").replace(" ", "_")
    s = _SAFE.sub("_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s or fallback


def format_acq(dt: datetime | None) -> str:
    if dt is None:
        return "UNKNOWN"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y%m%dT%H%M")


def product_id(
    *,
    area_id: str | None = None,
    pilot_id: str | None = None,
    s1_product_id: str | None = None,
    scene_id: str | None = None,
    acquisition_start: datetime | None,
    baseline_version_no: str | None,
    algo_profile_id: str,
    prod_ver: str = "v1",
) -> str:
    baseline = _tok(baseline_version_no or "NOBASE")
    return "_".join(
        [
            "SARAP_FLOOD",
            _tok(area_id or pilot_id, "AREA"),
            _tok(s1_product_id or scene_id, "SCENE"),
            format_acq(acquisition_start),
            baseline,
            _tok(algo_profile_id, "s1_grd_flood_v1"),
            _tok(prod_ver, "v1"),
        ]
    )
