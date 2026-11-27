"""Emergency-map GeoPDF.

The page is a map image plus a legend image. The map viewport carries an ISO
32000 geospatial measure (GPTS in EPSG:4326) so a GIS can place the page.
Chinese text is rasterized with the bundled CJK subset. No GDAL.
"""

from __future__ import annotations

import zlib
from pathlib import Path
from typing import Any

import numpy as np
from pyproj import Transformer

from sarap_engine.algo.grid import GridSpec

try:
    from PIL import Image, ImageDraw, ImageFont

    HAS_PIL = True
except Exception:  # pragma: no cover
    HAS_PIL = False
    Image = ImageDraw = ImageFont = None  # type: ignore

_PAGE_W = 842.0
_PAGE_H = 595.0
_MAP_BOX = (32.0, 36.0, 520.0, 524.0)  # x, y, w, h in PDF points, y up
_LEGEND_BOX = (560.0, 36.0, 250.0, 524.0)

_SWATCHES = (
    ((79, 142, 160), "本底水体"),
    ((196, 92, 38), "本次淹没"),
    ((42, 111, 122), "提取水体"),
    ((201, 162, 39), "低置信"),
)


def _load_font(path: Path, size: int):
    if path.is_file():
        return ImageFont.truetype(str(path), size=size)
    return ImageFont.load_default()


def _fonts(size: int):
    """CJK subset has no Latin digits. ASCII is a separate face."""
    root = Path(__file__).resolve().parents[1] / "assets"
    cjk = _load_font(root / "SarapCJK.ttf", size)
    latin = _load_font(root / "SarapLatin.ttf", size)
    if not (root / "SarapCJK.ttf").is_file():
        for path in (
            Path("/usr/share/fonts/truetype/wqy/wqy-microhei.ttc"),
            Path("/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf"),
        ):
            if path.is_file():
                cjk = ImageFont.truetype(str(path), size=size)
                break
    return cjk, latin


def _draw_text(draw, xy: tuple[float, float], text: str, cjk, latin, fill) -> None:
    x, y = xy
    for char in text:
        font = latin if ord(char) < 128 else cjk
        draw.text((x, y), char, font=font, fill=fill)
        x += float(font.getlength(char))


def _wrap(text: str, width: int = 14) -> list[str]:
    text = " ".join(str(text).split())
    if not text:
        return []
    return [text[index : index + width] for index in range(0, len(text), width)]


def _legend_lines(emergency: dict[str, Any], product_id: str) -> list[str]:
    summary = emergency.get("summary") if isinstance(emergency.get("summary"), dict) else {}
    lines = [
        str(emergency.get("title") or "洪水应急图"),
        str(emergency.get("basis_label") or ""),
        f"成像 {emergency.get('acquisition_start') or '—'}",
        f"坐标系 {emergency.get('crs') or '—'}",
        f"分辨率 {emergency.get('resolution_m') or 10} m",
        f"产品 {product_id}",
    ]
    if emergency.get("baseline_version_id"):
        lines.append(f"本底 {emergency.get('baseline_version_id')}")
    label = emergency.get("inundation_label") or "范围面积"
    area = emergency.get("inundation_ha")
    lines.append(f"{label} {area if area is not None else '—'} ha")
    if emergency.get("impact_configured"):
        lines.append(
            f"受影响道路 {summary.get('affected_road_count', 0)} 条 / {summary.get('affected_road_length_m', 0)} m"
        )
        lines.append(
            f"受影响居民点 {summary.get('affected_settlement_count', 0)} 个 / {summary.get('affected_settlement_area_ha', 0)} ha"
        )
        lines.append(
            f"受影响行政区 {summary.get('affected_admin_count', 0)} 个 / {summary.get('affected_admin_area_ha', 0)} ha"
        )
    else:
        lines.append("未配置影响对象")
    lines.append("建议 4 小时出图，不是合同时效。")
    lines.append("上为北。第一版不提供水深。")
    for note in emergency.get("footnotes") or []:
        lines.extend(_wrap(str(note)))
    lines.append("制图系统 SARAP")
    return [line for line in lines if line]


def _draw_overlay(draw, collection: dict[str, Any], grid: GridSpec, scale: int, color: tuple[int, int, int], width: int) -> None:
    ox, resx, _, oy, _, resy = grid.affine()

    def pixel(x: float, y: float) -> tuple[float, float]:
        return (x - ox) / resx * scale, (y - oy) / resy * scale

    for feature in collection.get("features") or []:
        geometry = feature.get("geometry") or {}
        kind = geometry.get("type")
        coords = geometry.get("coordinates") or []
        lines: list[Any] = []
        if kind == "LineString":
            lines = [coords]
        elif kind == "MultiLineString":
            lines = list(coords)
        elif kind == "Polygon":
            lines = list(coords)
        elif kind == "MultiPolygon":
            lines = [ring for polygon in coords for ring in polygon]
        for line in lines:
            if len(line) < 2:
                continue
            draw.line([pixel(float(pt[0]), float(pt[1])) for pt in line], fill=color, width=width)


def render_map_image(
    rgba: np.ndarray,
    grid: GridSpec,
    impact_layers: dict[str, Any] | None,
    *,
    max_px: int = 480,
) -> Image.Image:
    height, width = rgba.shape[:2]
    scale = max(1, min(8, max_px // max(height, width, 1)))
    grown = np.repeat(np.repeat(rgba, scale, axis=0), scale, axis=1)
    plate = Image.new("RGBA", (grown.shape[1], grown.shape[0]), (232, 236, 238, 255))
    sprite = Image.fromarray(grown, mode="RGBA")
    plate.alpha_composite(sprite)
    draw = ImageDraw.Draw(plate)
    overlays = impact_layers or {}
    if overlays.get("impact_admin_poly"):
        _draw_overlay(draw, overlays["impact_admin_poly"], grid, scale, (90, 106, 116), 2)
    if overlays.get("impact_settlement"):
        _draw_overlay(draw, overlays["impact_settlement"], grid, scale, (166, 124, 28), 3)
    if overlays.get("impact_road"):
        _draw_overlay(draw, overlays["impact_road"], grid, scale, (120, 96, 40), 3)
    return plate.convert("RGB")


def render_legend(emergency: dict[str, Any], product_id: str) -> Image.Image:
    cjk, latin = _fonts(22)
    small_cjk, small_latin = _fonts(18)
    lines = _legend_lines(emergency, product_id)
    width = 520
    swatch_h = 36 * len(_SWATCHES)
    height = 28 + swatch_h + 8 + 30 * len(lines) + 24
    image = Image.new("RGB", (width, height), (244, 247, 248))
    draw = ImageDraw.Draw(image)
    y = 16
    for color, label in _SWATCHES:
        draw.rectangle((16, y, 48, y + 22), fill=color)
        _draw_text(draw, (60, y), label, cjk, latin, (20, 32, 40))
        y += 36
    y += 8
    for line in lines:
        _draw_text(draw, (16, y), line, small_cjk, small_latin, (20, 32, 40))
        y += 30
    return image


def _rgb_bytes(image: Image.Image) -> tuple[bytes, int, int]:
    rgb = image.convert("RGB")
    width, height = rgb.size
    return rgb.tobytes(), width, height


def _num(value: float) -> str:
    text = f"{value:.5f}".rstrip("0").rstrip(".")
    return text if text not in {"", "-0"} else "0"


def _image_object(rgb: bytes, width: int, height: int) -> bytes:
    compressed = zlib.compress(rgb, 6)
    header = (
        f"<< /Type /XObject /Subtype /Image /Width {width} /Height {height} "
        f"/ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /FlateDecode /Length {len(compressed)} >>\nstream\n"
    ).encode()
    return header + compressed + b"\nendstream"


def _corners(grid: GridSpec, width: int, height: int) -> list[tuple[float, float]]:
    ox, resx, _, oy, _, resy = grid.affine()

    def xy(col: float, row: float) -> tuple[float, float]:
        return ox + col * resx, oy + row * resy

    # LL, UL, UR, LR in pixel-edge space. Row 0 is the north edge.
    return [xy(0, height), xy(0, 0), xy(width, 0), xy(width, height)]


def _geographic_corners(grid: GridSpec, width: int, height: int) -> list[tuple[float, float]]:
    transformer = Transformer.from_crs(grid.crs, "EPSG:4326", always_xy=True)
    lons, lats = transformer.transform(*zip(*_corners(grid, width, height), strict=True))
    return [(float(lat), float(lon)) for lat, lon in zip(lats, lons, strict=True)]


def _pdf(objects: list[bytes]) -> bytes:
    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{index} 0 obj\n".encode()
        out += obj
        if not obj.endswith(b"\n"):
            out += b"\n"
        out += b"endobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for offset in offsets[1:]:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        f"trailer<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n"
    ).encode()
    return bytes(out)


def build_emergency_geopdf(
    rgba: np.ndarray,
    grid: GridSpec,
    *,
    emergency: dict[str, Any] | None,
    impact_layers: dict[str, Any] | None,
    product_id: str,
) -> bytes:
    if not HAS_PIL:
        raise RuntimeError("GeoPDF needs Pillow")
    info = dict(emergency or {})
    info.setdefault("crs", grid.crs)
    info.setdefault("resolution_m", grid.res_m)
    map_image = render_map_image(rgba, grid, impact_layers)
    legend = render_legend(info, product_id)
    map_rgb, map_w, map_h = _rgb_bytes(map_image)
    legend_rgb, legend_w, legend_h = _rgb_bytes(legend)
    geographic = _geographic_corners(grid, rgba.shape[1], rgba.shape[0])
    gpts = " ".join(_num(value) for pair in geographic for value in pair)
    latlong = gpts
    mx, my, mw, mh = _MAP_BOX
    lx, ly, lw, lh = _LEGEND_BOX
    pdf_corners = [
        (mx, my),
        (mx, my + mh),
        (mx + mw, my + mh),
        (mx + mw, my),
    ]
    xy_points = " ".join(_num(value) for point in pdf_corners for value in point)
    content = (
        f"q\n{_num(mw)} 0 0 {_num(mh)} {_num(mx)} {_num(my)} cm\n/Im0 Do\nQ\n"
        f"q\n{_num(lw)} 0 0 {_num(lh)} {_num(lx)} {_num(ly)} cm\n/Im1 Do\nQ\n"
    ).encode()
    content_obj = f"<< /Length {len(content)} >>\nstream\n".encode() + content + b"endstream"
    bbox = " ".join(_num(value) for value in (mx, my, mx + mw, my + mh))
    epsg = (grid.crs or "").replace("EPSG:", "").replace("epsg:", "") or "0"
    page = (
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 842 595]\n"
        "/Resources << /XObject << /Im0 5 0 R /Im1 6 0 R >> >>\n"
        "/Contents 4 0 R\n"
        f"/VP [ << /Type /Viewport /BBox [{bbox}] /Name (SARAP map) /Measure <<\n"
        "/Type /Measure /Subtype /GEO /Bounds [0 0 0 1 1 1 1 0]\n"
        f"/GPTS [{gpts}] /LPTS [0 0 0 1 1 1 1 0]\n"
        "/GCS << /Type /GEOGCS /EPSG 4326 >>\n"
        ">> >> ]\n"
        "/LGIDict << /Type /LGIDict /Version (2.1) /Projection << /Type /Projection "
        "/ProjectionType /GEO /Datum (WGS84) >>\n"
        f"/Registration [ << /Type /Registration /CS (EPSG:{epsg}) /XYPoints [{xy_points}] "
        f"/LatLongPoints [{latlong}] >> ] >>\n"
        ">>"
    )
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Count 1 /Kids [3 0 R] >>",
        page.encode(),
        content_obj,
        _image_object(map_rgb, map_w, map_h),
        _image_object(legend_rgb, legend_w, legend_h),
    ]
    return _pdf(objects)
