"""SNAP 生产插件：渲染 graph、调用 gpt、检查输出。无 gpt 时明确失败，不改走 mock。"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from sarap_engine.algo.grid import GridSpec
from sarap_engine.constants import EngineError, ErrorCode
from sarap_engine.plugins.base import PluginContext, PluginResult, PreprocessResult
from sarap_engine.plugins.snap.runner import (
    find_gpt,
    graph_variables,
    render_graph,
    run_gpt,
    should_apply_border_noise,
)
from sarap_engine.products.raster_io import HAS_RASTERIO, read_raster


class SnapPlugin:
    name = "snap"
    capabilities = ["s1_grd_flood_v1", "gpt"]

    def __init__(self, gpt_binary: str = "gpt", timeout: float = 2400.0) -> None:
        self.gpt_binary = gpt_binary
        self.timeout = timeout

    def validate(self, context: PluginContext) -> None:
        if find_gpt(self.gpt_binary) is None:
            raise EngineError(
                ErrorCode.GPT_NOT_FOUND,
                f"生产模式 snap 需要 SNAP gpt，但系统找不到可执行文件 {self.gpt_binary!r}。"
                "不会改走 mock 插件。请安装 SNAP 并确保 gpt 在 PATH 中，或改用 execution_mode=mock。",
                retryable=False,
            )
        if not context.scene.has_vv:
            raise EngineError(ErrorCode.NO_VV, "输入缺少 VV 极化，无法提取水体", retryable=False)
        uri = context.scene.input_uri
        if not uri:
            raise EngineError(ErrorCode.INPUT_MISSING, "缺少 Sentinel-1 输入路径 input_uri", retryable=False)
        if "://" not in uri and not Path(uri).exists():
            raise EngineError(ErrorCode.INPUT_MISSING, f"输入路径不存在: {uri}", retryable=False)

    def run(self, context: PluginContext) -> PluginResult:
        self.validate(context)
        snap_dir = context.work_dir / "snap"
        snap_dir.mkdir(parents=True, exist_ok=True)
        output = snap_dir / "s1_sigma0_db.tif"
        aoi = context.pilot.aoi_wkt or "POLYGON((0 0,1 0,1 1,0 1,0 0))"
        variables = graph_variables(
            input_uri=context.scene.input_uri or "",
            output_uri=str(output),
            aoi_wkt=aoi,
            profile=context.profile,
            map_projection=context.pilot.analysis_crs,
            grid_origin_x=context.pilot.grid.origin_x,
            grid_origin_y=context.pilot.grid.origin_y,
            polarizations=context.scene.polarizations,
        )
        apply_bn = should_apply_border_noise(
            context.scene.ipf_version,
            force=context.profile.snap.force_border_noise_removal,
        )
        xml = render_graph(variables, apply_border_noise=apply_bn)
        run_gpt(xml, snap_dir, gpt_binary=self.gpt_binary, timeout=self.timeout)
        if not output.exists():
            raise EngineError(
                ErrorCode.SNAP_OUTPUT_INVALID,
                f"gpt 已返回成功但未找到输出: {output}",
                retryable=True,
            )
        if not HAS_RASTERIO:
            raise EngineError(
                ErrorCode.SNAP_OUTPUT_INVALID,
                "gpt 已产出 GeoTIFF，但当前环境未安装 rasterio/GDAL，无法读取 Sigma0_VV_dB 进入后处理。",
                retryable=False,
            )
        arr, grid = read_raster(output)
        # 单波段回退：把整幅当作 VV dB（完整多波段适配需按 SNAP 波段名读取）
        vv = np.asarray(arr, dtype=np.float64)
        nodata = ~np.isfinite(vv)
        preprocess = PreprocessResult(
            vv_db=vv,
            vh_db=None,
            incidence=None,
            dem=None,
            slope=None,
            layover=None,
            shadow=None,
            urban=None,
            nodata=nodata,
            grid=grid if isinstance(grid, GridSpec) else GridSpec(
                crs=context.pilot.analysis_crs,
                res_m=context.pilot.grid.res_m,
                origin_x=context.pilot.grid.origin_x,
                origin_y=context.pilot.grid.origin_y,
                width=vv.shape[1],
                height=vv.shape[0],
            ),
            orbit_type=context.scene.orbit_type,
            snap_version=None,
            polarization="VV_only",
        )
        return PluginResult(preprocess=preprocess, notes=["snap_gpt"])
