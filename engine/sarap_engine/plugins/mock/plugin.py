"""mock 插件：不调用 gpt，用合成小型 numpy 栅格走真实 extract/change/qc/package 算法。"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from sarap_engine.algo.grid import GridSpec
from sarap_engine.constants import EngineError, ErrorCode
from sarap_engine.plugins.base import PluginContext, PluginResult, PreprocessResult
from sarap_engine.products.raster_io import write_raster


def synthesize(
    grid: GridSpec,
    *,
    height: int = 80,
    width: int = 80,
    seed: int = 0,
    include_baseline_hint: bool = False,
) -> dict[str, np.ndarray]:
    """
    合成场景（10 m 网格）：
    - 左侧开阔水体（暗 VV）
    - 右侧旱地
    - 若干小于 MMU 的碎斑
    - 一块建成区压在水面上（应被降为低置信）
    - 一块阴影/陡坡
    - 部分像元入射角超限
    - 可选：本底水体覆盖左侧一部分
    """
    rng = np.random.default_rng(seed)
    vv = np.full((height, width), -8.0, dtype=np.float32)  # 旱地偏亮
    vh = np.full((height, width), -15.0, dtype=np.float32)
    # 左侧连片水体
    vv[:, :30] = -20.5
    vh[:, :30] = -26.0
    # 水体加轻微噪声，便于直方图
    vv += rng.normal(0, 0.3, size=vv.shape).astype(np.float32)
    vh += rng.normal(0, 0.3, size=vh.shape).astype(np.float32)

    # 碎斑（远小于 0.3 ha = 30 像元）
    vv[5:7, 50:52] = -21.0
    vv[10:12, 60:62] = -21.0

    urban = np.zeros((height, width), dtype=bool)
    urban[20:35, 10:25] = True  # 压在水体上

    shadow = np.zeros((height, width), dtype=bool)
    slope = np.zeros((height, width), dtype=np.float32)
    shadow[50:60, 5:18] = True
    slope[50:60, 5:18] = 22.0

    layover = np.zeros((height, width), dtype=bool)
    layover[70:75, 70:78] = True

    incidence = np.full((height, width), 36.0, dtype=np.float32)
    incidence[0:5, :] = 22.0  # 超限，不应进确定水

    nodata = np.zeros((height, width), dtype=bool)
    nodata[-2:, -2:] = True

    baseline = np.zeros((height, width), dtype=np.uint8)
    baseline_valid = np.ones((height, width), dtype=bool)
    # 本底覆盖左侧 0–18 列（部分与当期水体重叠，18–30 列为潜在本次淹没）
    baseline[:, :18] = 1
    # 右侧一角本底缺测
    baseline_valid[40:55, 20:28] = False
    baseline[40:55, 20:28] = 0

    return {
        "vv_db": vv,
        "vh_db": vh,
        "incidence": incidence,
        "slope": slope,
        "urban": urban,
        "shadow": shadow,
        "layover": layover,
        "nodata": nodata,
        "baseline_water": baseline,
        "baseline_valid": baseline_valid,
    }


class MockPlugin:
    name = "mock"
    capabilities = ["s1_grd_flood_v1", "synthetic"]

    def validate(self, context: PluginContext) -> None:
        # mock 不要求真实 SAFE / gpt；若明确声明无 VV 则仍失败
        if context.scene.polarizations and not context.scene.has_vv:
            raise EngineError(ErrorCode.NO_VV, "输入缺少 VV 极化，无法提取水体", retryable=False)

    def run(self, context: PluginContext) -> PluginResult:
        self.validate(context)
        h = int(context.pilot.grid.height or 80)
        w = int(context.pilot.grid.width or 80)
        grid = GridSpec(
            crs=context.pilot.analysis_crs,
            res_m=context.pilot.grid.res_m,
            origin_x=context.pilot.grid.origin_x,
            origin_y=context.pilot.grid.origin_y,
            width=w,
            height=h,
            transform=context.pilot.grid.affine(),
        )
        data = synthesize(grid, height=h, width=w)
        # 若任务指定了合成本底路径则由工作流读取；这里把数组放到工作目录供可选使用
        prep_dir = context.work_dir / "mock"
        prep_dir.mkdir(parents=True, exist_ok=True)
        for key, arr in data.items():
            np.save(prep_dir / f"{key}.npy", arr)
        write_raster(prep_dir / "sigma0_vv_db", data["vv_db"], grid)
        context.extras["synthetic"] = data
        preprocess = PreprocessResult(
            vv_db=data["vv_db"],
            vh_db=data["vh_db"],
            incidence=data["incidence"],
            dem=None,
            slope=data["slope"],
            layover=data["layover"],
            shadow=data["shadow"],
            urban=data["urban"],
            nodata=data["nodata"],
            grid=grid,
            orbit_type=context.scene.orbit_type or "precise",
            snap_version=None,
            polarization="VV+VH" if context.scene.has_vh else "VV_only",
            extras={
                "baseline_water": data["baseline_water"],
                "baseline_valid": data["baseline_valid"],
                "mock": True,
            },
        )
        return PluginResult(preprocess=preprocess, notes=["mock_synthetic_no_gpt"])
