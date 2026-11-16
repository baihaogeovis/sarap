
from __future__ import annotations

import numpy as np

from sarap_engine.algo.threshold import estimate_threshold


def test_unimodal_falls_back_to_t_default():
    rng = np.random.default_rng(1)
    # 单峰：全部旱地，均值约 -8 dB
    vv = rng.normal(-8.0, 0.4, size=400)
    result = estimate_threshold(vv, t_default=-18.0, t_clamp=(-23.0, -14.0), min_samples=64)
    assert result.source == "default"
    assert result.T == -18.0
    assert result.bimodal is False


def test_bimodal_clamped_when_auto_outside_range():
    rng = np.random.default_rng(2)
    # 水体峰极暗（约 -28），旱地约 -6，自适应阈值往往会低于 -23，必须夹逼
    water = rng.normal(-28.0, 0.8, size=400)
    land = rng.normal(-6.0, 0.8, size=400)
    vv = np.concatenate([water, land])
    result = estimate_threshold(vv, t_default=-18.0, t_clamp=(-23.0, -14.0), min_samples=64)
    assert result.T_auto is not None
    assert result.T_auto < -23.0 or result.source == "auto_clamped"
    assert result.source == "auto_clamped"
    assert result.T == -23.0
    assert result.bimodal is True


def test_bimodal_auto_within_clamp():
    rng = np.random.default_rng(3)
    water = rng.normal(-22.0, 0.5, size=500)
    land = rng.normal(-8.0, 0.5, size=500)
    vv = np.concatenate([water, land])
    result = estimate_threshold(vv, t_default=-18.0, t_clamp=(-23.0, -14.0), min_samples=64)
    assert result.bimodal is True
    assert result.source in {"auto", "auto_clamped"}
    assert -23.0 <= result.T <= -14.0
