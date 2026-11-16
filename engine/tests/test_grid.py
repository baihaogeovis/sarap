
from __future__ import annotations

import pytest

from sarap_engine.algo.grid import GridMisaligned, GridSpec, assert_grids_aligned
from sarap_engine.constants import ErrorCode


def test_aligned_grids_pass():
    a = GridSpec("EPSG:4548", 10.0, 0.0, 0.0, 80, 80)
    b = GridSpec("EPSG:4548", 10.0, 0.0, 0.0, 80, 80)
    assert_grids_aligned(a, b, require_same_shape=True)


def test_subpixel_origin_shift_fails():
    a = GridSpec("EPSG:4548", 10.0, 0.0, 0.0, 80, 80)
    b = GridSpec("EPSG:4548", 10.0, 0.5, 0.0, 80, 80)  # 0.5 m 亚像元偏移
    with pytest.raises(GridMisaligned) as exc:
        assert_grids_aligned(a, b, require_same_shape=True)
    assert exc.value.code == ErrorCode.GRID_MISALIGNED
    assert exc.value.retryable is False


def test_crs_mismatch_fails():
    a = GridSpec("EPSG:4548", 10.0, 0.0, 0.0)
    b = GridSpec("EPSG:3857", 10.0, 0.0, 0.0)
    with pytest.raises(GridMisaligned, match="CRS"):
        assert_grids_aligned(a, b)


def test_resolution_mismatch_fails():
    a = GridSpec("EPSG:4548", 10.0, 0.0, 0.0)
    b = GridSpec("EPSG:4548", 20.0, 0.0, 0.0)
    with pytest.raises(GridMisaligned, match="分辨率"):
        assert_grids_aligned(a, b)
