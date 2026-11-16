
from __future__ import annotations

import numpy as np

from sarap_engine.algo.qc import apply_risk_downgrade
from sarap_engine.constants import QcFlag, UrbanPolicy, qc_bit


def test_urban_default_downgrade_to_lowconf_not_deleted_or_hard():
    hard = np.zeros((5, 5), dtype=bool)
    hard[1:4, 1:4] = True
    low = np.zeros((5, 5), dtype=bool)
    flags = np.zeros((5, 5), dtype=np.uint16)
    nodata = np.zeros((5, 5), dtype=bool)
    urban = np.zeros((5, 5), dtype=bool)
    urban[2, 2] = True  # 中心像元在建成区
    out = apply_risk_downgrade(
        hard,
        low,
        qc_flags=flags,
        nodata=nodata,
        urban=urban,
        urban_policy=UrbanPolicy.DOWNGRADE,
        mark_edge=False,
    )
    assert not out.hard_water[2, 2]
    assert out.lowconf[2, 2]
    assert out.qc_flags[2, 2] & qc_bit(QcFlag.URBAN)
    # 非建成区确定水保留
    assert out.hard_water[1, 1]
    # 不得被删成“什么都没有”
    assert not (out.nodata[2, 2] and not out.lowconf[2, 2])


def test_urban_keep_with_flag_stays_hard():
    hard = np.array([[True]], dtype=bool)
    low = np.array([[False]], dtype=bool)
    flags = np.zeros((1, 1), dtype=np.uint16)
    nodata = np.array([[False]], dtype=bool)
    urban = np.array([[True]], dtype=bool)
    out = apply_risk_downgrade(
        hard,
        low,
        qc_flags=flags,
        nodata=nodata,
        urban=urban,
        urban_policy=UrbanPolicy.KEEP_WITH_FLAG,
        mark_edge=False,
    )
    assert out.hard_water[0, 0]
    assert not out.lowconf[0, 0]
    assert out.qc_flags[0, 0] & qc_bit(QcFlag.URBAN)
