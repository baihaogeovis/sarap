
from __future__ import annotations

import numpy as np

from sarap_engine.algo.extract import extract_water, mmu_pixels


def test_mmu_pixels_default():
    # 0.3 ha / 100 m² = 30 个 10 m 像元
    assert mmu_pixels(0.3, 10.0) == 30


def test_mmu_removes_small_patches_keeps_large():
    vv = np.full((40, 40), -8.0, dtype=np.float32)
    # 大正斑：6x6=36 > 30
    vv[2:8, 2:8] = -20.0
    # 小碎斑：2x2=4 < 30
    vv[20:22, 20:22] = -20.0
    vv[30:32, 30:31] = -20.0
    nodata = np.zeros_like(vv, dtype=bool)
    result = extract_water(
        vv,
        nodata=nodata,
        t_default=-18.0,
        t_clamp=(-23.0, -14.0),
        mmu_ha=0.3,
        res_m=10.0,
        use_vh_constraint=False,
    )
    assert result.hard_water[4, 4]
    assert not result.hard_water[20, 20]
    assert not result.hard_water[30, 30]
    assert result.mmu_removed[20, 20]
    assert result.mmu_removed[30, 30]
    assert not result.mmu_removed[4, 4]
