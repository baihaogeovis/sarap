"""ProcessingPlugin 协议：name、capabilities、validate、run。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import numpy as np

from sarap_engine.algo.grid import GridSpec
from sarap_engine.domain.algo_profile import AlgoProfile
from sarap_engine.domain.pilot import PilotConfig
from sarap_engine.domain.scene import SceneMeta


@dataclass
class PluginContext:
    job_id: str
    work_dir: Path
    scene: SceneMeta
    pilot: PilotConfig
    profile: AlgoProfile
    execution_mode: str
    baseline_uri: str | None = None
    baseline_version_id: str | None = None
    baseline_asset_id: str | None = None
    baseline_type: str | None = None
    extras: dict[str, Any] = field(default_factory=dict)


@dataclass
class PreprocessResult:
    """SNAP / mock 预处理输出：σ0(dB) 与辅助波段，已落到分析网格。"""

    vv_db: np.ndarray
    vh_db: np.ndarray | None
    incidence: np.ndarray | None
    dem: np.ndarray | None
    slope: np.ndarray | None
    layover: np.ndarray | None
    shadow: np.ndarray | None
    urban: np.ndarray | None
    nodata: np.ndarray
    grid: GridSpec
    orbit_type: str = "precise"
    snap_version: str | None = None
    polarization: str = "VV+VH"
    extras: dict[str, Any] = field(default_factory=dict)


@dataclass
class PluginResult:
    preprocess: PreprocessResult
    notes: list[str] = field(default_factory=list)


class ProcessingPlugin(Protocol):
    name: str
    capabilities: list[str]

    def validate(self, context: PluginContext) -> None:
        """校验输入与能力；不通过应抛 EngineError。"""
        ...

    def run(self, context: PluginContext) -> PluginResult:
        """执行预处理（gpt 或合成数据）。后处理由共享工作流完成。"""
        ...
