"""Turn an embedded RGBA display raster into XYZ tiles and a COG.

The engine stores the pixels with the product, in the analysis CRS. Web Mercator
is only the tile index. Draft products are not linked from the default map.
"""

from __future__ import annotations

import base64
import struct
import zlib
from typing import Any

import numpy as np
from pyproj import Transformer
from pyproj.exceptions import CRSError

from app.services.cog import encode_rgba_cog

_HALF = 20037508.342789244
_TILE = 256
_MAX_PIXELS = 2_000_000
_TRANSFORMERS: dict[tuple[str, str], Transformer] = {}
_EMPTY_PNG: dict[int, bytes] = {}


def _transformer(source: str, target: str) -> Transformer:
    key = (source, target)
    cached = _TRANSFORMERS.get(key)
    if cached is None:
        cached = Transformer.from_crs(source, target, always_xy=True)
        _TRANSFORMERS[key] = cached
    return cached


def decode_display(metadata: dict[str, Any] | None) -> tuple[np.ndarray, dict[str, Any]] | None:
    display = (metadata or {}).get("display")
    if not isinstance(display, dict):
        return None
    if display.get("encoding") != "rgba-raw" or int(display.get("samples") or 0) != 4:
        return None
    try:
        width = int(display["width"])
        height = int(display["height"])
        transform = [float(value) for value in display["transform"]]
        raw = base64.b64decode(str(display.get("pixels_b64") or ""), validate=True)
    except (KeyError, TypeError, ValueError):
        return None
    if len(transform) != 6 or width <= 0 or height <= 0:
        return None
    if width * height > _MAX_PIXELS or len(raw) != width * height * 4:
        return None
    if not str(display.get("crs") or "").strip():
        return None
    rgba = np.frombuffer(raw, dtype=np.uint8).reshape(height, width, 4)
    payload = dict(display)
    payload["transform"] = transform
    payload["width"] = width
    payload["height"] = height
    return rgba, payload


def _png_chunk(tag: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)


def encode_png(rgba: np.ndarray) -> bytes:
    height, width = rgba.shape[:2]
    raw = b"".join(b"\x00" + np.ascontiguousarray(rgba[row]).tobytes() for row in range(height))
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + _png_chunk(b"IHDR", ihdr) + _png_chunk(b"IDAT", zlib.compress(raw, 6)) + _png_chunk(b"IEND", b"")


def empty_png(size: int = _TILE) -> bytes:
    cached = _EMPTY_PNG.get(size)
    if cached is None:
        cached = encode_png(np.zeros((size, size, 4), dtype=np.uint8))
        _EMPTY_PNG[size] = cached
    return cached


def bounds_4326(display: dict[str, Any]) -> list[float] | None:
    try:
        ox, resx, _, oy, _, resy = display["transform"]
        width, height = int(display["width"]), int(display["height"])
        corners = [
            (ox, oy),
            (ox + width * resx, oy),
            (ox + width * resx, oy + height * resy),
            (ox, oy + height * resy),
        ]
        transformer = _transformer(str(display["crs"]), "EPSG:4326")
        lons, lats = transformer.transform([pt[0] for pt in corners], [pt[1] for pt in corners])
    except (CRSError, KeyError, TypeError, ValueError):
        return None
    if not all(np.isfinite(lons)) or not all(np.isfinite(lats)):
        return None
    return [float(min(lons)), float(min(lats)), float(max(lons)), float(max(lats))]


def _footprint_3857(display: dict[str, Any]) -> tuple[float, float, float, float] | None:
    try:
        ox, resx, _, oy, _, resy = display["transform"]
        width, height = int(display["width"]), int(display["height"])
        corners = [
            (ox, oy),
            (ox + width * resx, oy),
            (ox + width * resx, oy + height * resy),
            (ox, oy + height * resy),
        ]
        transformer = _transformer(str(display["crs"]), "EPSG:3857")
        xs, ys = transformer.transform([pt[0] for pt in corners], [pt[1] for pt in corners])
    except (CRSError, KeyError, TypeError, ValueError):
        return None
    if not all(np.isfinite(xs)) or not all(np.isfinite(ys)):
        return None
    return float(min(xs)), float(min(ys)), float(max(xs)), float(max(ys))


def tile_bounds(z: int, x: int, y: int) -> tuple[float, float, float, float]:
    span = (2 * _HALF) / (2**z)
    minx = -_HALF + x * span
    maxy = _HALF - y * span
    return minx, maxy - span, minx + span, maxy


def render_tile(rgba: np.ndarray, display: dict[str, Any], z: int, x: int, y: int, size: int = _TILE) -> bytes:
    minx, miny, maxx, maxy = tile_bounds(z, x, y)
    footprint = _footprint_3857(display)
    if footprint is None:
        return empty_png(size)
    fx0, fy0, fx1, fy1 = footprint
    if maxx < fx0 or minx > fx1 or maxy < fy0 or miny > fy1:
        return empty_png(size)
    try:
        transformer = _transformer("EPSG:3857", str(display["crs"]))
    except CRSError:
        return empty_png(size)
    xs = minx + (np.arange(size) + 0.5) * (maxx - minx) / size
    ys = maxy - (np.arange(size) + 0.5) * (maxy - miny) / size
    xx, yy = np.meshgrid(xs, ys)
    ax, ay = transformer.transform(xx.ravel(), yy.ravel())
    ox, resx, _, oy, _, resy = display["transform"]
    if resx == 0 or resy == 0:
        return empty_png(size)
    col = np.floor((ax - ox) / resx).astype(np.int32)
    row = np.floor((ay - oy) / resy).astype(np.int32)
    flat = np.zeros((size * size, 4), dtype=np.uint8)
    valid = (col >= 0) & (col < rgba.shape[1]) & (row >= 0) & (row < rgba.shape[0])
    if np.any(valid):
        flat[valid] = rgba[row[valid], col[valid]]
    if not np.any(flat[:, 3]):
        return empty_png(size)
    return encode_png(flat.reshape(size, size, 4))


def cog_bytes(rgba: np.ndarray, display: dict[str, Any]) -> bytes:
    ox, resx, _, oy, _, resy = display["transform"]
    return encode_rgba_cog(
        np.ascontiguousarray(rgba),
        crs=str(display["crs"]),
        origin_x=float(ox),
        origin_y=float(oy),
        res_x=abs(float(resx)),
        res_y=abs(float(resy)),
    )


def sample_hit(rgba: np.ndarray, display: dict[str, Any], lon: float, lat: float) -> bool:
    try:
        transformer = _transformer("EPSG:4326", str(display["crs"]))
        x, y = transformer.transform(float(lon), float(lat))
    except (CRSError, TypeError, ValueError):
        return False
    ox, resx, _, oy, _, resy = display["transform"]
    if resx == 0 or resy == 0 or not (np.isfinite(x) and np.isfinite(y)):
        return False
    col = int(np.floor((float(x) - ox) / resx))
    row = int(np.floor((float(y) - oy) / resy))
    if col < 0 or row < 0 or col >= rgba.shape[1] or row >= rgba.shape[0]:
        return False
    return int(rgba[row, col, 3]) > 0
