"""Minimal tiled GeoTIFF writer.

Produces an uncompressed, tiled, georeferenced TIFF that readers can use as a
Cloud Optimized GeoTIFF: the IFD sits before the tiles, tiles are ordered
left-to-right and top-to-bottom, and overviews follow the full-resolution IFD
when the image is larger than 512 px. No GDAL or rasterio required.
"""

from __future__ import annotations

import math
import struct
from pathlib import Path

import numpy as np
from pyproj import CRS

TAG_IMAGE_WIDTH = 256
TAG_IMAGE_LENGTH = 257
TAG_BITS_PER_SAMPLE = 258
TAG_COMPRESSION = 259
TAG_PHOTOMETRIC = 262
TAG_SAMPLES_PER_PIXEL = 277
TAG_PLANAR = 284
TAG_TILE_WIDTH = 322
TAG_TILE_LENGTH = 323
TAG_TILE_OFFSETS = 273
TAG_TILE_BYTE_COUNTS = 279
TAG_EXTRA_SAMPLES = 338
TAG_MODEL_PIXEL_SCALE = 33550
TAG_MODEL_TIEPOINT = 33922
TAG_GEO_KEY_DIRECTORY = 34735

TYPE_SHORT = 3
TYPE_LONG = 4
TYPE_DOUBLE = 12


class _Tag:
    def __init__(self, code: int, typ: int, count: int, data: bytes) -> None:
        self.code = code
        self.typ = typ
        self.count = count
        self.data = data


def _shorts(code: int, values: tuple[int, ...]) -> _Tag:
    return _Tag(code, TYPE_SHORT, len(values), struct.pack("<" + "H" * len(values), *values))


def _longs(code: int, values: tuple[int, ...]) -> _Tag:
    return _Tag(code, TYPE_LONG, len(values), struct.pack("<" + "I" * len(values), *values))


def _doubles(code: int, values: tuple[float, ...]) -> _Tag:
    return _Tag(code, TYPE_DOUBLE, len(values), struct.pack("<" + "d" * len(values), *values))


def _serialize_ifd(tags: list[_Tag], next_offset: int, start: int) -> bytes:
    ordered = sorted(tags, key=lambda tag: tag.code)
    count = len(ordered)
    ifd_len = 2 + 12 * count + 4
    cursor = start + ifd_len
    extra = bytearray()
    values: list[bytes] = []
    for tag in ordered:
        if len(tag.data) <= 4:
            values.append(tag.data.ljust(4, b"\x00"))
            continue
        if cursor % 2:
            extra.append(0)
            cursor += 1
        values.append(struct.pack("<I", cursor))
        extra += tag.data
        cursor += len(tag.data)
    out = bytearray(struct.pack("<H", count))
    for tag, value in zip(ordered, values, strict=True):
        out += struct.pack("<HHI", tag.code, tag.typ, tag.count)
        out += value
    out += struct.pack("<I", next_offset)
    out += extra
    return bytes(out)


def _geo_keys(epsg: int, projected: bool) -> bytes:
    if projected:
        keys = ((1024, 0, 1, 1), (1025, 0, 1, 1), (3072, 0, 1, epsg))
    else:
        keys = ((1024, 0, 1, 2), (1025, 0, 1, 1), (2048, 0, 1, epsg))
    data = [1, 1, 0, len(keys)]
    for key, loc, count, value in keys:
        data.extend((key, loc, count, value))
    return struct.pack("<" + "H" * len(data), *data)


def _tiles(rgba: np.ndarray, tile: int) -> list[bytes]:
    height, width = rgba.shape[:2]
    blobs: list[bytes] = []
    rows = math.ceil(height / tile)
    cols = math.ceil(width / tile)
    for row in range(rows):
        for col in range(cols):
            r0, c0 = row * tile, col * tile
            patch = np.zeros((tile, tile, 4), dtype=np.uint8)
            r1, c1 = min(r0 + tile, height), min(c0 + tile, width)
            patch[: r1 - r0, : c1 - c0] = rgba[r0:r1, c0:c1]
            blobs.append(np.ascontiguousarray(patch).tobytes())
    return blobs


def _downsample(rgba: np.ndarray) -> np.ndarray:
    height, width = rgba.shape[:2]
    next_h, next_w = max(1, height // 2), max(1, width // 2)
    rows = np.minimum(np.arange(next_h) * 2, height - 1)
    cols = np.minimum(np.arange(next_w) * 2, width - 1)
    return np.ascontiguousarray(rgba[np.ix_(rows, cols)])


def _tags_for(
    rgba: np.ndarray,
    *,
    tile: int,
    origin_x: float,
    origin_y: float,
    res_x: float,
    res_y: float,
    epsg: int,
    projected: bool,
    offsets: tuple[int, ...],
    counts: tuple[int, ...],
) -> list[_Tag]:
    height, width = rgba.shape[:2]
    return [
        _longs(TAG_IMAGE_WIDTH, (width,)),
        _longs(TAG_IMAGE_LENGTH, (height,)),
        _shorts(TAG_BITS_PER_SAMPLE, (8, 8, 8, 8)),
        _shorts(TAG_COMPRESSION, (1,)),
        _shorts(TAG_PHOTOMETRIC, (2,)),
        _longs(TAG_TILE_OFFSETS, offsets),
        _shorts(TAG_SAMPLES_PER_PIXEL, (4,)),
        _longs(TAG_TILE_BYTE_COUNTS, counts),
        _shorts(TAG_PLANAR, (1,)),
        _longs(TAG_TILE_WIDTH, (tile,)),
        _longs(TAG_TILE_LENGTH, (tile,)),
        _shorts(TAG_EXTRA_SAMPLES, (2,)),
        _doubles(TAG_MODEL_PIXEL_SCALE, (abs(res_x), abs(res_y), 0.0)),
        _doubles(TAG_MODEL_TIEPOINT, (0.0, 0.0, 0.0, origin_x, origin_y, 0.0)),
        _Tag(TAG_GEO_KEY_DIRECTORY, TYPE_SHORT, len(_geo_keys(epsg, projected)) // 2, _geo_keys(epsg, projected)),
    ]


def encode_rgba_cog(
    rgba: np.ndarray,
    *,
    crs: str,
    origin_x: float,
    origin_y: float,
    res_x: float,
    res_y: float,
    tile: int = 256,
) -> bytes:
    """RGBA image, row 0 at the north edge. `res_y` is the north-up pixel height (positive)."""
    image = np.ascontiguousarray(rgba, dtype=np.uint8)
    if image.ndim != 3 or image.shape[2] != 4:
        raise ValueError("COG writer expects an RGBA image")
    if image.size == 0:
        raise ValueError("COG writer expects a non-empty image")
    description = CRS.from_user_input(crs)
    epsg = description.to_epsg()
    if epsg is None:
        raise ValueError(f"COG writer needs an EPSG code, got {crs}")
    projected = bool(description.is_projected)
    levels: list[tuple[np.ndarray, float]] = [(image, 1.0)]
    current = image
    factor = 1.0
    while max(current.shape[0], current.shape[1]) > 512:
        current = _downsample(current)
        factor *= 2.0
        levels.append((current, factor))

    placeholder_sizes: list[int] = []
    tile_groups: list[list[bytes]] = []
    for level, _factor in levels:
        blobs = _tiles(level, tile)
        tile_groups.append(blobs)
        counts = tuple(len(blob) for blob in blobs)
        offsets = tuple(0 for _ in blobs)
        tags = _tags_for(
            level,
            tile=tile,
            origin_x=origin_x,
            origin_y=origin_y,
            res_x=res_x * _factor,
            res_y=res_y * _factor,
            epsg=epsg,
            projected=projected,
            offsets=offsets,
            counts=counts,
        )
        placeholder_sizes.append(len(_serialize_ifd(tags, 0, 0)))

    ifd_offsets: list[int] = []
    cursor = 8
    for size in placeholder_sizes:
        ifd_offsets.append(cursor)
        cursor += size
    tile_cursor = cursor
    assigned: list[tuple[tuple[int, ...], tuple[int, ...]]] = []
    flat_tiles: list[bytes] = []
    for blobs in tile_groups:
        offsets_list: list[int] = []
        counts_list: list[int] = []
        for blob in blobs:
            offsets_list.append(tile_cursor)
            counts_list.append(len(blob))
            tile_cursor += len(blob)
            flat_tiles.append(blob)
        assigned.append((tuple(offsets_list), tuple(counts_list)))

    ifd_blobs: list[bytes] = []
    for index, (level, factor) in enumerate(levels):
        offsets, counts = assigned[index]
        tags = _tags_for(
            level,
            tile=tile,
            origin_x=origin_x,
            origin_y=origin_y,
            res_x=res_x * factor,
            res_y=res_y * factor,
            epsg=epsg,
            projected=projected,
            offsets=offsets,
            counts=counts,
        )
        next_offset = ifd_offsets[index + 1] if index + 1 < len(levels) else 0
        blob = _serialize_ifd(tags, next_offset, ifd_offsets[index])
        if len(blob) != placeholder_sizes[index]:
            raise RuntimeError("COG IFD size changed after tile offsets were assigned")
        ifd_blobs.append(blob)

    header = b"II" + struct.pack("<HI", 42, ifd_offsets[0])
    return header + b"".join(ifd_blobs) + b"".join(flat_tiles)


def write_rgba_cog(path: Path, rgba: np.ndarray, *, crs: str, origin_x: float, origin_y: float, res_x: float, res_y: float) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        encode_rgba_cog(rgba, crs=crs, origin_x=origin_x, origin_y=origin_y, res_x=res_x, res_y=res_y)
    )
    return path
