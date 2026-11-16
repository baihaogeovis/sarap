"""栅格读写。有 rasterio 则写 GeoTIFF/COG；否则写 npy + grid.json 侧车。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from sarap_engine.algo.grid import GridSpec

try:
    import rasterio
    from rasterio.crs import CRS
    from rasterio.transform import Affine

    HAS_RASTERIO = True
except Exception:  # pragma: no cover - 环境无 GDAL 时
    HAS_RASTERIO = False
    rasterio = None  # type: ignore


def write_raster(
    path: Path,
    array: np.ndarray,
    grid: GridSpec,
    *,
    nodata: float | int | None = None,
    dtype: str | None = None,
) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    arr = np.asarray(array)
    if HAS_RASTERIO:
        out = path if path.suffix.lower() in {".tif", ".tiff"} else path.with_suffix(".tif")
        # Affine.from_gdal 接受 GDAL 顺序 (origin_x, resx, 0, origin_y, 0, -resy)
        transform = Affine.from_gdal(*_to_gdal(grid))
        crs = grid.crs
        profile = {
            "driver": "GTiff",
            "height": arr.shape[0],
            "width": arr.shape[1],
            "count": 1,
            "dtype": dtype or arr.dtype,
            "crs": CRS.from_string(crs) if not str(crs).upper().startswith("INVALID") else None,
            "transform": transform,
            "tiled": True,
            "blockxsize": 256,
            "blockysize": 256,
            "compress": "deflate",
        }
        if nodata is not None:
            profile["nodata"] = nodata
        with rasterio.open(out, "w", **profile) as dst:
            dst.write(arr, 1)
        return out

    npy_path = path.with_suffix(".npy")
    meta_path = path.with_suffix(".grid.json")
    np.save(npy_path, arr)
    meta_path.write_text(
        json.dumps(
            {
                "crs": grid.crs,
                "res_m": grid.res_m,
                "origin_x": grid.origin_x,
                "origin_y": grid.origin_y,
                "width": int(arr.shape[1]),
                "height": int(arr.shape[0]),
                "transform": list(grid.affine()),
                "dtype": str(arr.dtype),
                "nodata": nodata,
                "npy": npy_path.name,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return npy_path


def read_raster(path: Path) -> tuple[np.ndarray, GridSpec]:
    path = Path(path)
    if path.suffix.lower() in {".tif", ".tiff"} and HAS_RASTERIO:
        with rasterio.open(path) as src:
            arr = src.read(1)
            t = src.transform
            crs = src.crs.to_string() if src.crs else ""
            grid = GridSpec(
                crs=crs,
                res_m=float(t.a),
                origin_x=float(t.c),
                origin_y=float(t.f),
                width=src.width,
                height=src.height,
                transform=(float(t.c), float(t.a), float(t.b), float(t.f), float(t.d), float(t.e)),
            )
            return arr, grid
    npy = path if path.suffix == ".npy" else path.with_suffix(".npy")
    meta = path.with_suffix(".grid.json")
    if not npy.is_file() and path.is_file() and path.suffix == ".npy":
        npy = path
    arr = np.load(npy)
    info = json.loads(meta.read_text(encoding="utf-8")) if meta.is_file() else {}
    tr = info.get("transform")
    grid = GridSpec(
        crs=info.get("crs") or "EPSG:4548",
        res_m=float(info.get("res_m") or 10),
        origin_x=float(info.get("origin_x") or 0),
        origin_y=float(info.get("origin_y") or 0),
        width=int(info.get("width") or arr.shape[1]),
        height=int(info.get("height") or arr.shape[0]),
        transform=tuple(tr) if tr else None,  # type: ignore[arg-type]
    )
    return arr, grid


def _to_gdal(grid: GridSpec) -> tuple[float, float, float, float, float, float]:
    a = grid.affine()
    # our affine is (origin_x, resx, 0, origin_y, 0, -resy) which IS GDAL order already
    return a
