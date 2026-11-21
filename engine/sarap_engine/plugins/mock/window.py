"""Place the mock raster window on the area AOI, snapped to that area's grid.

The analysis CRS, grid origin, resolution, and AOI all come from the job.
Nothing here names a basin or substitutes a fixed CRS.
"""

from __future__ import annotations

import math
import re

_POLYGON = re.compile(r"POLYGON\s*\(\((.*?)\)\)", re.IGNORECASE | re.DOTALL)


def _polygon_xy(wkt: str) -> list[tuple[float, float]]:
    match = _POLYGON.search(wkt or "")
    if not match:
        raise ValueError("mock window placement needs a simple POLYGON AOI")
    coords: list[tuple[float, float]] = []
    for pair in match.group(1).split(","):
        parts = pair.split()
        if len(parts) < 2:
            continue
        coords.append((float(parts[0]), float(parts[1])))
    if len(coords) < 4:
        raise ValueError("AOI polygon is incomplete")
    return coords


def _snap_floor(value: float, origin: float, res: float) -> float:
    n = math.floor((value - origin) / res + 1e-9)
    return origin + n * res


def _snap_ceil(value: float, origin: float, res: float) -> float:
    n = math.ceil((value - origin) / res - 1e-9)
    return origin + n * res


def _intersects(
    west: float,
    north: float,
    span_x: float,
    span_y: float,
    minx: float,
    miny: float,
    maxx: float,
    maxy: float,
) -> bool:
    south = north - span_y
    east = west + span_x
    return west < maxx and east > minx and south < maxy and north > miny


def resolve_mock_window_origin(
    *,
    analysis_crs: str,
    aoi_crs: str,
    aoi_wkt: str | None,
    grid_origin_x: float,
    grid_origin_y: float,
    res_m: float,
    width: int,
    height: int,
) -> tuple[float, float]:
    """Return the north-west corner of the synthetic window in the analysis CRS.

    Falls back to the area grid origin when the AOI cannot be placed on that grid.
    The returned corner stays on the area grid (integer pixels from grid_origin).
    """
    fallback = (float(grid_origin_x), float(grid_origin_y))
    if not aoi_wkt or width <= 0 or height <= 0 or res_m <= 0:
        return fallback
    crs = (analysis_crs or "").strip().upper()
    if crs in {"EPSG:4326", "EPSG:4490", "CRS84", "OGC:CRS84"}:
        # A geographic analysis CRS is not a metre grid. Keep the stored origin.
        return fallback
    try:
        ring = _polygon_xy(aoi_wkt)
        from pyproj import Transformer

        transformer = Transformer.from_crs(aoi_crs or "EPSG:4490", analysis_crs, always_xy=True)
        xs, ys = transformer.transform([p[0] for p in ring], [p[1] for p in ring])
        minx, maxx = float(min(xs)), float(max(xs))
        miny, maxy = float(min(ys)), float(max(ys))
    except Exception:
        return fallback
    if not all(math.isfinite(v) for v in (minx, maxx, miny, maxy)):
        return fallback
    if maxx <= minx or maxy <= miny:
        return fallback

    res = float(res_m)
    span_x = width * res
    span_y = height * res
    ox, oy = float(grid_origin_x), float(grid_origin_y)
    # A geographic rectangle is not a rectangle after projection. Anchoring the
    # window on the bbox north-west corner can leave the open-water side
    # outside the AOI. Center the window when it fits, so the demo patch sits
    # on the area.
    if maxx - minx >= span_x and maxy - miny >= span_y:
        cx = (minx + maxx) / 2.0
        cy = (miny + maxy) / 2.0
        west = _snap_floor(cx - span_x / 2.0, ox, res)
        north = _snap_ceil(cy + span_y / 2.0, oy, res)
        if _intersects(west, north, span_x, span_y, minx, miny, maxx, maxy):
            return west, north
    west = _snap_ceil(minx, ox, res)
    north = _snap_floor(maxy, oy, res)
    if not _intersects(west, north, span_x, span_y, minx, miny, maxx, maxy):
        west = _snap_floor(minx, ox, res)
        north = _snap_floor(maxy, oy, res)
    if not _intersects(west, north, span_x, span_y, minx, miny, maxx, maxy):
        return fallback
    return west, north
