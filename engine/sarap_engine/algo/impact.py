"""Overlay roads, settlements, and admin units on the analysis grid.

Statistics use the area analysis CRS at the product resolution (10 m).
Web Mercator and geographic CRSs are refused. Reprojection to EPSG:4326
happens later, only for the web map.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from sarap_engine.algo.grid import GridSpec
from sarap_engine.constants import AREA_LIMITATION, LIMITATIONS, ClassCode
from sarap_engine.domain.pilot import ImpactAssets
from sarap_engine.fixtures.loader import PUBLIC_VALIDATION_FIXTURE, fixture_collection

_WEB_MERCATOR = {"EPSG:3857", "EPSG:900913", "EPSG:102100", "EPSG:102113"}
_GEOGRAPHIC = {"EPSG:4326", "EPSG:4490", "CRS84", "OGC:CRS84"}
_POLYGON_TYPES = {"admin_county", "admin_township", "settlement", "cropland"}
_LINE_TYPES = {"road"}
_LAYER_FOR = {
    "admin_county": "impact_admin_poly",
    "admin_township": "impact_admin_poly",
    "road": "impact_road",
    "settlement": "impact_settlement",
    "cropland": "impact_cropland",
}
_PRIMARY_METRIC = {
    "road": "affected_length_m",
    "settlement": "affected_area_ha",
    "admin_county": "affected_area_ha",
    "admin_township": "affected_area_ha",
    "cropland": "affected_area_ha",
}

ROAD_LENGTH_NOTE = "道路长度为中心线与范围相交的长度，未做路宽改正。"
ANALYSIS_NOTE = "统计在区域分析坐标系的 10 m 网格上计算，网页地图只做经纬度展示。"


def _crs(value: str | None) -> str:
    text = (value or "").strip().upper().replace(" ", "")
    if text in {"CRS84", "OGC:CRS84", "CRS:84"}:
        return "EPSG:4326"
    if text.startswith("EPSG:"):
        return text
    if text.isdigit():
        return f"EPSG:{text}"
    return text


def analysis_crs_blocked(crs: str | None) -> str | None:
    """Return a note when this CRS must not be used for impact statistics."""
    code = _crs(crs)
    if code in _WEB_MERCATOR:
        return "分析坐标系是 Web Mercator，交叉统计已跳过。分析必须在区域 analysis_crs 的米制网格上进行。"
    if code in _GEOGRAPHIC:
        return "分析坐标系是地理坐标，交叉统计已跳过。分析必须在区域 analysis_crs 的 10 m 网格上进行。"
    return None


@dataclass
class ImpactObject:
    object_type: str
    object_id: str
    object_name: str
    parent_admin_code: str
    geometry: dict[str, Any]


def _map_positions(coords: Any, fn) -> Any:
    if isinstance(coords, (list, tuple)) and coords and isinstance(coords[0], (int, float)):
        x, y = fn(float(coords[0]), float(coords[1]))
        return [x, y]
    if isinstance(coords, list):
        return [_map_positions(item, fn) for item in coords]
    raise ValueError("geometry coordinates are not positions")


def _local_to_world(grid: GridSpec):
    ox, _, _, oy, _, _ = grid.affine()

    def convert(x: float, y: float) -> tuple[float, float]:
        # Fixture axes: east and south from the window's north-west corner.
        return ox + x, oy - y

    return convert


def _transformer(source_crs: str, target_crs: str):
    from pyproj import Transformer
    from pyproj.exceptions import CRSError

    try:
        return Transformer.from_crs(source_crs, target_crs, always_xy=True)
    except CRSError as exc:
        raise ValueError(f"cannot reproject {source_crs} to {target_crs}") from exc


def _read_collection(reference: str) -> dict[str, Any] | None:
    token = (reference or "").strip()
    if token == PUBLIC_VALIDATION_FIXTURE or token.endswith("public_validation_window"):
        return json.loads(json.dumps(fixture_collection()))
    path = Path(token)
    if not path.is_file():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(doc, dict) or doc.get("type") != "FeatureCollection":
        return None
    return doc


def _place_collection(doc: dict[str, Any], grid: GridSpec) -> dict[str, Any]:
    space = str(doc.get("coord_space") or "")
    source = _crs(str(doc.get("crs") or ""))
    target = _crs(grid.crs)
    if space == "local_window_m":
        convert = _local_to_world(grid)

        def fn(x: float, y: float) -> tuple[float, float]:
            return convert(x, y)

    elif not source:
        raise ValueError("impact geometry has no CRS")
    elif source == target or (source in _GEOGRAPHIC and target in _GEOGRAPHIC):

        def fn(x: float, y: float) -> tuple[float, float]:
            return x, y

    else:
        transformer = _transformer(source, target)

        def fn(x: float, y: float) -> tuple[float, float]:
            east, north = transformer.transform(x, y)
            return float(east), float(north)

    placed = dict(doc)
    features = []
    for feature in doc.get("features") or []:
        if not isinstance(feature, dict):
            continue
        geometry = feature.get("geometry") or {}
        coords = geometry.get("coordinates")
        if coords is None:
            continue
        features.append(
            {
                **feature,
                "geometry": {
                    "type": geometry.get("type"),
                    "coordinates": _map_positions(coords, fn),
                },
            }
        )
    placed["features"] = features
    placed["crs"] = target
    return placed


def load_impact_objects(
    impact_assets: ImpactAssets | dict[str, Any] | None,
    grid: GridSpec,
) -> tuple[list[ImpactObject], str | None]:
    """Load configured objects onto `grid`.

    A missing file or an unknown token yields no objects and a note.
    It does not invent stand-in polygons.
    """
    blocked = analysis_crs_blocked(grid.crs)
    if blocked:
        return [], blocked
    if isinstance(impact_assets, ImpactAssets):
        raw = {
            "admin_county": impact_assets.admin_county,
            "admin_township": impact_assets.admin_township,
            "road": impact_assets.road,
            "settlement": impact_assets.settlement,
            "cropland": impact_assets.cropland,
        }
    elif isinstance(impact_assets, dict):
        raw = dict(impact_assets)
    else:
        raw = {}
    configured = {key: value for key, value in raw.items() if value}
    if not configured:
        return [], None

    objects: list[ImpactObject] = []
    failed = False
    seen: set[tuple[str, str]] = set()
    for object_type, reference in configured.items():
        if object_type not in _LAYER_FOR:
            continue
        try:
            doc = _read_collection(str(reference))
            if doc is None:
                failed = True
                continue
            placed = _place_collection(doc, grid)
        except (ValueError, TypeError, OSError):
            failed = True
            continue
        for feature in placed.get("features") or []:
            props = feature.get("properties") or {}
            if props.get("object_type") != object_type:
                continue
            geometry = feature.get("geometry") or {}
            if geometry.get("type") not in {"Polygon", "MultiPolygon", "LineString", "MultiLineString"}:
                continue
            object_id = str(props.get("object_id") or "")
            key = (object_type, object_id)
            if key in seen:
                continue
            seen.add(key)
            objects.append(
                ImpactObject(
                    object_type=object_type,
                    object_id=object_id,
                    object_name=str(props.get("object_name") or object_id or object_type),
                    parent_admin_code=str(props.get("parent_admin_code") or ""),
                    geometry=geometry,
                )
            )
    if objects:
        note = "已在分析网格上叠加道路、居民点与行政区。"
        if failed:
            note += "部分几何无法读取，未计入。"
        return objects, note
    if failed:
        return [], "已配置影响对象，但几何无法读取，不出交叉结论。"
    return [], "已配置影响对象，但没有可叠加的几何，不出交叉结论。"


def _ring_mask(xx: np.ndarray, yy: np.ndarray, ring: list) -> np.ndarray:
    inside = np.zeros(xx.shape, dtype=bool)
    if len(ring) < 4:
        return inside
    closed = ring[:-1] if ring[0] == ring[-1] else ring
    count = len(closed)
    for index in range(count):
        x1, y1 = float(closed[index][0]), float(closed[index][1])
        x2, y2 = float(closed[(index + 1) % count][0]), float(closed[(index + 1) % count][1])
        if y1 == y2:
            continue
        crosses = (y1 > yy) != (y2 > yy)
        x_at = (x2 - x1) * (yy - y1) / (y2 - y1) + x1
        inside ^= crosses & (xx < x_at)
    return inside


def _polygon_mask(geometry: dict[str, Any], grid: GridSpec, shape: tuple[int, int]) -> np.ndarray:
    height, width = shape
    ox, resx, _, oy, _, resy = grid.affine()
    xs = ox + (np.arange(width) + 0.5) * resx
    ys = oy + (np.arange(height) + 0.5) * resy
    xx = np.broadcast_to(xs, (height, width))
    yy = np.broadcast_to(ys[:, None], (height, width))
    kind = geometry.get("type")
    coords = geometry.get("coordinates") or []
    mask = np.zeros(shape, dtype=bool)
    polygons = coords if kind == "MultiPolygon" else [coords]
    for polygon in polygons:
        if not polygon:
            continue
        part = _ring_mask(xx, yy, polygon[0])
        for hole in polygon[1:]:
            part &= ~_ring_mask(xx, yy, hole)
        mask |= part
    return mask


def _cell(x: float, y: float, grid: GridSpec, height: int, width: int) -> tuple[int, int] | None:
    ox, resx, _, oy, _, resy = grid.affine()
    if resx == 0 or resy == 0:
        return None
    col = math.floor((x - ox) / resx)
    row = math.floor((y - oy) / resy)
    if row < 0 or col < 0 or row >= height or col >= width:
        return None
    return row, col


def _lines(geometry: dict[str, Any]) -> list[list]:
    kind = geometry.get("type")
    coords = geometry.get("coordinates") or []
    if kind == "LineString":
        return [coords]
    if kind == "MultiLineString":
        return list(coords)
    return []


def _length_m(coords: list, mask: np.ndarray, grid: GridSpec) -> float:
    if len(coords) < 2:
        return 0.0
    height, width = mask.shape
    step = max(abs(float(grid.res_m)) / 4.0, 0.5)
    total = 0.0
    for start, end in zip(coords, coords[1:], strict=False):
        x0, y0 = float(start[0]), float(start[1])
        x1, y1 = float(end[0]), float(end[1])
        dist = math.hypot(x1 - x0, y1 - y0)
        if dist == 0:
            continue
        pieces = max(1, int(math.ceil(dist / step)))
        ds = dist / pieces
        for index in range(pieces):
            t = (index + 0.5) / pieces
            cell = _cell(x0 + (x1 - x0) * t, y0 + (y1 - y0) * t, grid, height, width)
            if cell is not None and mask[cell]:
                total += ds
    return total


def _scope_masks(class_map: np.ndarray, *, has_baseline: bool) -> dict[str, np.ndarray]:
    if has_baseline:
        default = class_map == int(ClassCode.FLOOD_EVENT)
    else:
        default = class_map == int(ClassCode.EXTRACTED_WATER)
    low = default | (class_map == int(ClassCode.WATER_LOWCONF))
    return {"default": default, "including_lowconf": low}


def _metric_rows(
    obj: ImpactObject,
    *,
    scope: str,
    value_m2: float | None,
    value_m: float | None,
    denominator_m2: float | None,
    basis: str,
    baseline_version_id: str | None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    extra = {
        "parent_admin_code": obj.parent_admin_code,
        "baseline_version_id": baseline_version_id,
        "basis": basis,
        "label": obj.object_name,
    }
    if value_m is not None and value_m > 0:
        metres = int(round(value_m))
        rows.append(_row(obj, "affected_length_m", metres, "m", scope, extra))
        rows.append(_row(obj, "affected_length_km", round(metres / 1000.0, 2), "km", scope, extra))
    if value_m2 is not None and value_m2 > 0:
        metres2 = int(round(value_m2))
        rows.append(_row(obj, "affected_area_m2", metres2, "m2", scope, extra))
        rows.append(_row(obj, "affected_area_ha", round(metres2 / 10000.0, 2), "ha", scope, extra))
        if denominator_m2 and denominator_m2 > 0:
            rows.append(
                _row(obj, "area_ratio", round(metres2 / denominator_m2, 4), "ratio", scope, extra)
            )
    return rows


def _row(obj: ImpactObject, metric: str, value: float, unit: str, scope: str, extra: dict) -> dict[str, Any]:
    return {
        "object_type": obj.object_type,
        "object_id": obj.object_id,
        "object_name": obj.object_name,
        "parent_admin_code": obj.parent_admin_code,
        "metric": metric,
        "value": value,
        "unit": unit,
        "scope": scope,
        "extra": dict(extra),
    }


def _primary_value(rows: list[dict[str, Any]], obj: ImpactObject, scope: str) -> float:
    metric = _PRIMARY_METRIC.get(obj.object_type)
    for row in rows:
        if row["object_id"] == obj.object_id and row["metric"] == metric and row["scope"] == scope:
            return float(row["value"])
    return 0.0


def overlay_impacts(
    class_map: np.ndarray,
    objects: list[ImpactObject],
    grid: GridSpec,
    *,
    res_m: float,
    has_baseline: bool,
    baseline_version_id: str | None = None,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    """Return cross-stat rows and analysis-CRS feature collections.

    Zero intersections are kept on the map layer and omitted from the table,
    so an unmeasured category is not filled with an empty shell.
    """
    cm = np.asarray(class_map)
    valid = cm != int(ClassCode.NODATA)
    scopes = _scope_masks(cm, has_baseline=has_baseline)
    basis = "flood_event" if has_baseline else "extracted_water"
    rows: list[dict[str, Any]] = []
    grouped: dict[str, list[dict[str, Any]]] = {}
    cell = float(res_m) * float(res_m)

    for obj in objects:
        layer_name = _LAYER_FOR.get(obj.object_type)
        if layer_name is None:
            continue
        kind = obj.geometry.get("type")
        measured: dict[str, tuple[float | None, float | None, float | None]] = {}
        if kind in {"Polygon", "MultiPolygon"} and obj.object_type in _POLYGON_TYPES:
            inside = _polygon_mask(obj.geometry, grid, cm.shape) & valid
            denominator = float(int(inside.sum()) * cell)
            for scope, mask in scopes.items():
                hit = float(int((inside & mask).sum()) * cell)
                measured[scope] = (hit, None, denominator)
        elif kind in {"LineString", "MultiLineString"} and obj.object_type in _LINE_TYPES:
            for scope, mask in scopes.items():
                length = 0.0
                for line in _lines(obj.geometry):
                    length += _length_m(line, mask, grid)
                measured[scope] = (None, length, None)
        else:
            continue
        for scope, (area, length, denominator) in measured.items():
            rows.extend(
                _metric_rows(
                    obj,
                    scope=scope,
                    value_m2=area,
                    value_m=length,
                    denominator_m2=denominator,
                    basis=basis,
                    baseline_version_id=baseline_version_id,
                )
            )
        affected = _primary_value(rows, obj, "default") > 0
        unit = "m" if obj.object_type == "road" else "ha"
        grouped.setdefault(layer_name, []).append(
            {
                "type": "Feature",
                "properties": {
                    "name": obj.object_name,
                    "object_type": obj.object_type,
                    "object_id": obj.object_id,
                    "affected": affected,
                    "value": _primary_value(rows, obj, "default"),
                    "unit": unit,
                    "scope": "default",
                    "basis": basis,
                },
                "geometry": obj.geometry,
            }
        )

    collections = {
        name: {"type": "FeatureCollection", "name": name, "crs": _crs(grid.crs), "features": features}
        for name, features in grouped.items()
        if features
    }
    return rows, collections


def _summary_from_rows(rows: list[dict[str, Any]], scope: str) -> dict[str, Any]:
    def pick(object_type: str, metric: str) -> list[dict[str, Any]]:
        return [
            row
            for row in rows
            if row.get("object_type") == object_type and row.get("metric") == metric and row.get("scope") == scope
        ]

    roads = pick("road", "affected_length_m")
    settlements = pick("settlement", "affected_area_ha")
    admins = pick("admin_county", "affected_area_ha") + pick("admin_township", "affected_area_ha")
    return {
        "affected_road_count": len(roads),
        "affected_road_length_m": int(round(sum(float(row["value"]) for row in roads))),
        "affected_settlement_count": len(settlements),
        "affected_settlement_area_ha": round(sum(float(row["value"]) for row in settlements), 2),
        "affected_admin_count": len(admins),
        "affected_admin_area_ha": round(sum(float(row["value"]) for row in admins), 2),
    }


def build_emergency_map(
    *,
    area_name: str,
    crs: str,
    res_m: float,
    has_baseline: bool,
    impact_configured: bool,
    cross_stats: list[dict[str, Any]],
    areas: dict[str, Any],
    acquisition_start: str | None,
    baseline_version_id: str | None,
    layer_names: list[str],
) -> dict[str, Any]:
    basis = "flood_event" if has_baseline else "extracted_water"
    basis_label = "本次淹没" if has_baseline else "提取水体（未扣本底）"
    title_kind = "洪水应急图" if has_baseline else "水体提取应急图"
    summary = _summary_from_rows(cross_stats, "default") if impact_configured else {}
    low = _summary_from_rows(cross_stats, "including_lowconf") if impact_configured else {}
    inundation = areas.get("flood_event_ha") if has_baseline else areas.get("extracted_water_ha")
    return {
        "title": f"{area_name}{title_kind}" if area_name else title_kind,
        "basis": basis,
        "basis_label": basis_label,
        "crs": crs,
        "resolution_m": res_m,
        "acquisition_start": acquisition_start,
        "baseline_version_id": baseline_version_id,
        "area_name": area_name,
        "impact_configured": impact_configured,
        "inundation_ha": inundation,
        "inundation_label": "本次淹没面积" if has_baseline else "提取水体面积（未扣本底）",
        "summary": summary,
        "summary_including_lowconf": low,
        "layers": layer_names,
        "footnotes": [AREA_LIMITATION, ROAD_LENGTH_NOTE, ANALYSIS_NOTE, *LIMITATIONS],
        "suggested_target_minutes": 240,
        "contract_commitment": False,
    }
