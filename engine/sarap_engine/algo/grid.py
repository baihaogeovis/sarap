"""与本底网格对齐校验。不对齐必须失败，禁止隐性平移或静默重采样。"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from sarap_engine.constants import EngineError, ErrorCode


class GridMisaligned(EngineError):
    def __init__(self, message: str) -> None:
        super().__init__(ErrorCode.GRID_MISALIGNED, message, retryable=False)


@dataclass(frozen=True)
class GridSpec:
    crs: str
    res_m: float
    origin_x: float
    origin_y: float
    width: int | None = None
    height: int | None = None
    # GDAL affine: x' = a + i*b + j*c ; y' = d + i*e + j*f  with (b,c,e,f) typically (res,0,0,-res)
    transform: tuple[float, float, float, float, float, float] | None = None

    def affine(self) -> tuple[float, float, float, float, float, float]:
        if self.transform is not None:
            return self.transform
        return (self.origin_x, self.res_m, 0.0, self.origin_y, 0.0, -abs(self.res_m))


def _crs_norm(crs: str) -> str:
    s = (crs or "").strip().upper().replace(" ", "")
    if s.startswith("EPSG:"):
        return s
    if s.isdigit():
        return f"EPSG:{s}"
    return s


def assert_grids_aligned(
    a: GridSpec,
    b: GridSpec,
    *,
    origin_tol_m: float = 1e-3,
    res_rtol: float = 1e-6,
    res_atol: float = 1e-6,
    require_same_shape: bool = False,
) -> None:
    """校验 CRS、分辨率、网格原点（以及可选的行列数）。失败抛 GridMisaligned。"""
    if _crs_norm(a.crs) != _crs_norm(b.crs):
        raise GridMisaligned(f"CRS 不一致: {a.crs} vs {b.crs}")

    ta, tb = a.affine(), b.affine()
    # 分辨率：仿射 (b, f) 或 res_m
    res_ax, res_ay = float(ta[1]), float(ta[5])
    res_bx, res_by = float(tb[1]), float(tb[5])
    if not (
        np.isclose(res_ax, res_bx, rtol=res_rtol, atol=res_atol)
        and np.isclose(res_ay, res_by, rtol=res_rtol, atol=res_atol)
    ):
        raise GridMisaligned(
            f"分辨率不一致: ({res_ax}, {res_ay}) vs ({res_bx}, {res_by})"
        )

    # 旋转/剪切项必须同为 0（或彼此相等）
    if not (
        np.isclose(ta[2], tb[2], atol=res_atol)
        and np.isclose(ta[4], tb[4], atol=res_atol)
    ):
        raise GridMisaligned("仿射剪切/旋转项不一致，禁止隐性变换")

    # 原点必须落在同一 10 m 网格。允许两者原点相差整数个像元（不同裁剪窗口），
    # 但不允许亚像元偏移。
    dx = ta[0] - tb[0]
    dy = ta[3] - tb[3]
    px = abs(res_ax) if res_ax else 1.0
    py = abs(res_ay) if res_ay else 1.0
    off_x = abs(dx / px - round(dx / px)) * px
    off_y = abs(dy / py - round(dy / py)) * py
    if off_x > origin_tol_m or off_y > origin_tol_m:
        raise GridMisaligned(
            f"网格原点不对齐（亚像元偏移 {off_x:.6f}, {off_y:.6f} m），必须重裁，禁止隐性平移"
        )

    if require_same_shape:
        if a.width != b.width or a.height != b.height:
            raise GridMisaligned(
                f"栅格形状不一致: {(a.width, a.height)} vs {(b.width, b.height)}"
            )
        # 同一窗口还要求原点完全相同
        if abs(dx) > origin_tol_m or abs(dy) > origin_tol_m:
            raise GridMisaligned(
                f"同尺寸栅格原点不一致: ({ta[0]}, {ta[3]}) vs ({tb[0]}, {tb[3]})"
            )
