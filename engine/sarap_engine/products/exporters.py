"""把分类结果写成产品文件：栅格、矢量（尽力）、metadata / qc_summary / 面积。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from sarap_engine.algo.grid import GridSpec
from sarap_engine.algo.morphology import label_connected
from sarap_engine.constants import ClassCode
from sarap_engine.products.models import ProductLayer, ProductManifest, ProductMetadata
from sarap_engine.products.raster_io import HAS_RASTERIO, write_raster

try:
    from PIL import Image

    HAS_PIL = True
except Exception:  # pragma: no cover
    HAS_PIL = False


# 色表（考虑打印与色弱：本底蓝、本次淹没橙红，不用红绿相对）
CLASS_COLORS = {
    0: (0, 0, 0, 0),
    1: (230, 230, 220, 255),
    2: (30, 90, 180, 255),
    3: (220, 90, 30, 255),
    4: (240, 190, 80, 255),
    5: (40, 130, 200, 255),
}


def _write_json(path: Path, data: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return path


def _layer(name: str, path: Path, media: str, *, empty: bool = False, note: str | None = None) -> ProductLayer:
    return ProductLayer(name=name, uri=str(path), media_type=media, empty=empty, note=note)


def write_class_rasters(
    out_dir: Path,
    class_map: np.ndarray,
    water_current: np.ndarray,
    flood_event: np.ndarray,
    qc_flags: np.ndarray,
    grid: GridSpec,
    *,
    has_baseline: bool,
) -> list[ProductLayer]:
    layers: list[ProductLayer] = []
    ext = ".tif" if HAS_RASTERIO else ".npy"
    p = write_raster(out_dir / f"class_map{ext}", class_map.astype(np.uint8), grid, nodata=0, dtype="uint8")
    layers.append(_layer("class_map", p, "image/tiff" if HAS_RASTERIO else "application/octet-stream"))
    p = write_raster(out_dir / f"water_current{ext}", water_current.astype(np.uint8), grid, nodata=0, dtype="uint8")
    layers.append(_layer("water_current", p, "image/tiff" if HAS_RASTERIO else "application/octet-stream"))
    p = write_raster(out_dir / f"qc_flags{ext}", qc_flags.astype(np.uint16), grid, dtype="uint16")
    layers.append(_layer("qc_flags", p, "image/tiff" if HAS_RASTERIO else "application/octet-stream"))
    if has_baseline:
        p = write_raster(out_dir / f"flood_event{ext}", flood_event.astype(np.uint8), grid, nodata=0, dtype="uint8")
        layers.append(_layer("flood_event", p, "image/tiff" if HAS_RASTERIO else "application/octet-stream"))
    else:
        # 可出空层，并在 note / metadata 标明不是「本次淹没」官方产品
        p = write_raster(
            out_dir / f"flood_event{ext}",
            np.zeros_like(flood_event, dtype=np.uint8),
            grid,
            nodata=0,
            dtype="uint8",
        )
        layers.append(
            _layer(
                "flood_event",
                p,
                "image/tiff" if HAS_RASTERIO else "application/octet-stream",
                empty=True,
                note="baseline_missing：空层，不得当作本次淹没发布",
            )
        )
    return layers


def _component_polygons(
    mask: np.ndarray,
    grid: GridSpec,
    *,
    class_code: int,
    product_id: str,
    res_m: float,
) -> list[dict[str, Any]]:
    """简易矢量化：每个连通域用外接矩形近似（无 shapely 时的可测试最小实现）。"""
    labels, n = label_connected(mask, connectivity=8)
    feats: list[dict[str, Any]] = []
    origin_x, resx, _, origin_y, _, resy = grid.affine()
    fid = 1
    for lab in range(1, n + 1):
        ys, xs = np.where(labels == lab)
        if ys.size == 0:
            continue
        r0, r1 = int(ys.min()), int(ys.max()) + 1
        c0, c1 = int(xs.min()), int(xs.max()) + 1
        x0 = origin_x + c0 * resx
        x1 = origin_x + c1 * resx
        y0 = origin_y + r0 * resy
        y1 = origin_y + r1 * resy
        # resy 通常为负，保证环方向
        ring = [[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]
        area_m2 = int(ys.size) * res_m * res_m
        feats.append(
            {
                "type": "Feature",
                "properties": {
                    "fid": fid,
                    "product_id": product_id,
                    "class_code": class_code,
                    "area_m2": int(round(area_m2)),
                    "area_ha": round(area_m2 / 10000.0, 2),
                    "perimeter_m": None,
                    "confidence": "high",
                    "flags": 0,
                },
                "geometry": {"type": "Polygon", "coordinates": [ring]},
            }
        )
        fid += 1
    return feats


def write_polygons(
    out_dir: Path,
    class_map: np.ndarray,
    grid: GridSpec,
    *,
    product_id: str,
    has_baseline: bool,
    res_m: float,
    acquisition_start: str | None = None,
    baseline_version_id: str | None = None,
) -> list[ProductLayer]:
    layers: list[ProductLayer] = []
    if has_baseline:
        current_mask = np.isin(
            class_map,
            [ClassCode.PERMANENT_OR_BASELINE_WATER, ClassCode.FLOOD_EVENT],
        )
        current_feats = []
        current_feats.extend(
            _component_polygons(
                class_map == ClassCode.PERMANENT_OR_BASELINE_WATER,
                grid,
                class_code=int(ClassCode.PERMANENT_OR_BASELINE_WATER),
                product_id=product_id,
                res_m=res_m,
            )
        )
        current_feats.extend(
            _component_polygons(
                class_map == ClassCode.FLOOD_EVENT,
                grid,
                class_code=int(ClassCode.FLOOD_EVENT),
                product_id=product_id,
                res_m=res_m,
            )
        )
        flood_feats = _component_polygons(
            class_map == ClassCode.FLOOD_EVENT,
            grid,
            class_code=int(ClassCode.FLOOD_EVENT),
            product_id=product_id,
            res_m=res_m,
        )
    else:
        current_mask = class_map == ClassCode.EXTRACTED_WATER
        current_feats = _component_polygons(
            current_mask,
            grid,
            class_code=int(ClassCode.EXTRACTED_WATER),
            product_id=product_id,
            res_m=res_m,
        )
        flood_feats = []

    def dump(name: str, feats: list[dict[str, Any]], *, empty: bool = False, note: str | None = None) -> ProductLayer:
        for f in feats:
            f["properties"]["acq_start"] = acquisition_start
            f["properties"]["baseline_version_id"] = baseline_version_id
        doc = {"type": "FeatureCollection", "features": feats, "name": name}
        path = _write_json(out_dir / f"{name}.geojson", doc)
        return _layer("application/geo+json" and name, path, "application/geo+json", empty=empty, note=note)

    # fix: _layer first arg is name
    layers.append(dump("water_current_poly", current_feats))
    if has_baseline:
        layers.append(dump("flood_event_poly", flood_feats))
    else:
        layers.append(
            dump(
                "flood_event_poly",
                flood_feats,
                empty=True,
                note="baseline_missing：空层，不得当作本次淹没发布",
            )
        )
    return layers


def _draw_overlay(draw, collection: dict[str, Any], grid, scale: int, color: tuple[int, int, int], width: int) -> None:
    ox, resx, _, oy, _, resy = grid.affine()

    def pixel(x: float, y: float) -> tuple[float, float]:
        col = (x - ox) / resx
        row = (y - oy) / resy
        return col * scale, row * scale

    for feature in collection.get("features") or []:
        geometry = feature.get("geometry") or {}
        kind = geometry.get("type")
        coords = geometry.get("coordinates") or []
        lines = []
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
            points = [pixel(float(pt[0]), float(pt[1])) for pt in line]
            draw.line(points, fill=color, width=width)


def write_thematic_png(
    out_dir: Path,
    class_map: np.ndarray,
    grid,
    *,
    emergency: dict[str, Any] | None = None,
    impact_layers: dict[str, Any] | None = None,
) -> ProductLayer | None:
    """Duty preview PNG: class grid, impact objects, and the key numbers.

    GeoPDF stays out of this version. Chinese captions are in emergency_map.json
    because the default bitmap font has no CJK glyphs.
    """
    if not HAS_PIL:
        return None
    from PIL import ImageDraw

    scale = 4
    height, width = class_map.shape
    small = np.zeros((height, width, 4), dtype=np.uint8)
    for code, color in CLASS_COLORS.items():
        small[class_map == code] = color
    rgba = np.repeat(np.repeat(small, scale, axis=0), scale, axis=1)
    map_img = Image.fromarray(rgba, mode="RGBA")
    draw = ImageDraw.Draw(map_img)
    overlays = impact_layers or {}
    if overlays.get("impact_admin_poly"):
        _draw_overlay(draw, overlays["impact_admin_poly"], grid, scale, (232, 238, 242), 1)
    if overlays.get("impact_settlement"):
        _draw_overlay(draw, overlays["impact_settlement"], grid, scale, (201, 162, 39), 2)
    if overlays.get("impact_road"):
        _draw_overlay(draw, overlays["impact_road"], grid, scale, (215, 192, 122), 2)

    panel_w = 280
    canvas = Image.new("RGBA", (map_img.width + panel_w, max(map_img.height, 360)), (15, 26, 34, 255))
    canvas.paste(map_img, (0, 0))
    pen = ImageDraw.Draw(canvas)
    summary = (emergency or {}).get("summary") or {}
    configured = bool((emergency or {}).get("impact_configured"))
    lines = [
        (emergency or {}).get("basis_label") or "water",
        f"area ha: {(emergency or {}).get('inundation_ha')}",
        f"CRS {((emergency or {}).get('crs') or '')}",
        f"{(emergency or {}).get('resolution_m') or 10} m",
    ]
    if configured:
        lines.extend(
            [
                f"roads: {summary.get('affected_road_count')} / {summary.get('affected_road_length_m')} m",
                f"settlements: {summary.get('affected_settlement_count')} / {summary.get('affected_settlement_area_ha')} ha",
                f"admin: {summary.get('affected_admin_count')} / {summary.get('affected_admin_area_ha')} ha",
            ]
        )
    lines.append("No water depth.")
    y = 12
    for line in lines:
        pen.text((map_img.width + 12, y), str(line), fill=(232, 238, 242, 255))
        y += 18
    path = out_dir / "thematic_map.png"
    canvas.convert("RGB").save(path)
    return ProductLayer(
        name="thematic_map",
        uri=str(path),
        media_type="image/png",
        note="应急专题图预览（PNG）。GeoPDF 不在本增量。",
    )


def package_product(
    out_dir: Path,
    *,
    metadata: ProductMetadata,
    qc_summary: dict[str, Any],
    impact_stats: dict[str, Any],
    class_map: np.ndarray,
    water_current: np.ndarray,
    flood_event: np.ndarray,
    qc_flags: np.ndarray,
    grid: GridSpec,
) -> ProductManifest:
    out_dir.mkdir(parents=True, exist_ok=True)
    has_baseline = metadata.flood_event_status != "baseline_missing"
    impact_layers = dict(impact_stats.pop("impact_layers", None) or {})
    emergency_map = impact_stats.pop("emergency_map", None)
    layers: list[ProductLayer] = []
    layers.extend(
        write_class_rasters(
            out_dir,
            class_map,
            water_current,
            flood_event,
            qc_flags,
            grid,
            has_baseline=has_baseline,
        )
    )
    acq = None
    if metadata.acquisition_start is not None:
        acq = metadata.acquisition_start.isoformat()
    layers.extend(
        write_polygons(
            out_dir,
            class_map,
            grid,
            product_id=metadata.product_id,
            has_baseline=has_baseline,
            res_m=metadata.resolution_m,
            acquisition_start=acq,
            baseline_version_id=metadata.baseline_version_id,
        )
    )
    for name, collection in impact_layers.items():
        path = _write_json(out_dir / f"{name}.geojson", collection)
        layers.append(_layer(name, path, "application/geo+json"))
    if isinstance(emergency_map, dict):
        emergency_path = _write_json(out_dir / "emergency_map.json", emergency_map)
        layers.append(_layer("emergency_map", emergency_path, "application/json"))
    png = write_thematic_png(out_dir, class_map, grid, emergency=emergency_map, impact_layers=impact_layers)
    if png is not None:
        layers.append(png)

    meta_path = _write_json(out_dir / "metadata.json", metadata.to_public_dict())
    layers.append(_layer("metadata", meta_path, "application/json"))
    qc_path = _write_json(out_dir / "qc_summary.json", qc_summary)
    layers.append(_layer("qc_summary", qc_path, "application/json"))
    impact_path = _write_json(out_dir / "impact_stats.json", impact_stats)
    layers.append(_layer("impact_stats", impact_path, "application/json"))
    # CSV 面积表
    csv_path = out_dir / "impact_stats.csv"
    rows = impact_stats.get("metrics") or []
    cross_rows = impact_stats.get("cross_stats") or []
    with csv_path.open("w", encoding="utf-8") as f:
        f.write("object_type,object_id,object_name,metric,value,unit,scope\n")
        for r in rows:
            f.write(
                f"extent,,{r.get('label','')},{r.get('metric','')},{r.get('value','')},"
                f"{r.get('unit','')},{r.get('scope','')}\n"
            )
        for r in cross_rows:
            f.write(
                f"{r.get('object_type','')},{r.get('object_id','')},{r.get('object_name','')},"
                f"{r.get('metric','')},{r.get('value','')},{r.get('unit','')},{r.get('scope','')}\n"
            )
    layers.append(_layer("impact_stats_csv", csv_path, "text/csv"))

    manifest = ProductManifest(
        product_id=metadata.product_id,
        layers=layers,
        metadata=metadata,
        qc_summary=qc_summary,
        impact_stats=impact_stats,
        work_dir=str(out_dir),
    )
    _write_json(out_dir / "manifest.json", json.loads(manifest.model_dump_json()))
    return manifest
