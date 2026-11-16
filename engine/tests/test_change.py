
from __future__ import annotations

import numpy as np
import pytest

from sarap_engine.algo.change import classify_with_baseline, classify_without_baseline
from sarap_engine.algo.grid import GridSpec
from sarap_engine.constants import ClassCode, FloodEventStatus, qc_bit, QcFlag


def test_without_baseline_uses_class_5_not_2_or_3():
    hard = np.zeros((4, 4), dtype=bool)
    hard[0, 0] = True
    hard[0, 1] = True
    low = np.zeros((4, 4), dtype=bool)
    low[1, 1] = True
    nodata = np.zeros((4, 4), dtype=bool)
    nodata[3, 3] = True
    flags = np.zeros((4, 4), dtype=np.uint16)
    result = classify_without_baseline(hard, low, nodata, flags)
    assert result.has_baseline is False
    assert result.flood_event_status == FloodEventStatus.BASELINE_MISSING.value
    assert set(np.unique(result.class_map)) <= {
        ClassCode.NODATA,
        ClassCode.NON_WATER,
        ClassCode.WATER_LOWCONF,
        ClassCode.EXTRACTED_WATER,
    }
    assert ClassCode.PERMANENT_OR_BASELINE_WATER not in result.class_map
    assert ClassCode.FLOOD_EVENT not in result.class_map
    assert result.class_map[0, 0] == ClassCode.EXTRACTED_WATER
    assert result.class_map[1, 1] == ClassCode.WATER_LOWCONF
    assert result.flood_event.sum() == 0
    assert result.water_current[0, 0] == 1


def test_baseline_subtract_official_formula():
    hard = np.zeros((3, 3), dtype=bool)
    hard[0, :] = True  # 当期确定水：第一行
    low = np.zeros((3, 3), dtype=bool)
    nodata = np.zeros((3, 3), dtype=bool)
    flags = np.zeros((3, 3), dtype=np.uint16)
    baseline = np.zeros((3, 3), dtype=bool)
    baseline[0, 0] = True  # 本底水仅 (0,0)
    valid = np.ones((3, 3), dtype=bool)
    grid = GridSpec("EPSG:4548", 10, 0, 0, 3, 3)
    result = classify_with_baseline(
        hard, low, nodata, flags, baseline, valid, current_grid=grid, baseline_grid=grid
    )
    assert result.has_baseline
    assert result.class_map[0, 0] == ClassCode.PERMANENT_OR_BASELINE_WATER
    assert result.class_map[0, 1] == ClassCode.FLOOD_EVENT
    assert result.class_map[0, 2] == ClassCode.FLOOD_EVENT
    assert ClassCode.EXTRACTED_WATER not in result.class_map
    assert result.flood_event[0, 1] == 1
    assert result.flood_event[0, 0] == 0


def test_baseline_nodata_must_not_count_as_flood():
    hard = np.zeros((2, 2), dtype=bool)
    hard[0, 0] = True
    hard[0, 1] = True
    low = np.zeros((2, 2), dtype=bool)
    nodata = np.zeros((2, 2), dtype=bool)
    flags = np.zeros((2, 2), dtype=np.uint16)
    baseline = np.zeros((2, 2), dtype=bool)
    valid = np.ones((2, 2), dtype=bool)
    valid[0, 1] = False  # 本底缺测
    result = classify_with_baseline(hard, low, nodata, flags, baseline, valid)
    assert result.class_map[0, 0] == ClassCode.FLOOD_EVENT  # 本底有效且非水
    assert result.class_map[0, 1] == ClassCode.WATER_LOWCONF  # 不得算本次淹没
    assert result.flood_event[0, 1] == 0
    assert result.qc_flags[0, 1] & qc_bit(QcFlag.BASELINE_GAP)
