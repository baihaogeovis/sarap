"""Serve published product vectors in EPSG:4326 for OpenLayers.

Analysis stays in the area CRS. This module only reprojects a copy for the web map.
Geographic exchange CRSs (EPSG:4490 / EPSG:4326) are already lon/lat and pass through.
"""

from __future__ import annotations

import math
import uuid
from typing import Any

from pyproj import Transformer
from pyproj.exceptions import CRSError
from sqlalchemy.orm import Session

from app.models import Area, ImpactStat, Product, ProductLayer

DISPLAY_CRS = "EPSG:4326"
_GEOGRAPHIC = {"EPSG:4326", "EPSG:4490", "CRS84", "OGC:CRS84"}
_VECTOR_KEYS = ("flood_event_poly", "water_current_poly")
_IMPACT_SPECS = (
    ("impact_admin_poly", "行政区", "admin", False),
    ("impact_road", "道路", "road", False),
    ("impact_settlement", "居民点", "settlement", True),
    ("impact_cropland", "耕地", "cropland", True),
)
_IMPACT_KEYS = tuple(item[0] for item in _IMPACT_SPECS)


def normalize_crs(value: str | None) -> str:
    text = (value or "").strip().upper().replace(" ", "")
    if text in {"CRS84", "OGC:CRS84", "CRS:84"}:
        return "EPSG:4326"
    if text.startswith("EPSG:"):
        return text
    if text.isdigit():
        return f"EPSG:{text}"
    return text


def is_geographic(crs: str) -> bool:
    return normalize_crs(crs) in _GEOGRAPHIC


def _as_feature_collection(doc: Any) -> dict[str, Any] | None:
    if not isinstance(doc, dict):
        return None
    kind = doc.get("type")
    if kind == "FeatureCollection" and isinstance(doc.get("features"), list):
        return doc
    if kind == "Feature":
        return {"type": "FeatureCollection", "features": [doc]}
    if kind in {"Polygon", "MultiPolygon", "Point", "LineString", "MultiPoint", "MultiLineString"}:
        return {"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {}, "geometry": doc}]}
    return None


def _transform_coords(coords: Any, fn) -> Any:
    if isinstance(coords, (list, tuple)) and coords and isinstance(coords[0], (int, float)):
        lon, lat = fn(float(coords[0]), float(coords[1]))
        if not (math.isfinite(lon) and math.isfinite(lat)):
            raise ValueError("reprojected coordinate is not finite")
        if not (-180.0 <= lon <= 180.0 and -90.0 <= lat <= 90.0):
            raise ValueError("reprojected coordinate is outside lon/lat range")
        return [round(lon, 6), round(lat, 6)]
    if isinstance(coords, list):
        return [_transform_coords(item, fn) for item in coords]
    raise ValueError("geometry coordinates are not a GeoJSON position")


def reproject_geojson(doc: dict[str, Any], source_crs: str) -> dict[str, Any]:
    """Return a FeatureCollection in EPSG:4326. Does not mutate `doc`."""
    collection = _as_feature_collection(doc)
    if collection is None:
        raise ValueError("not a GeoJSON feature collection")
    crs = normalize_crs(source_crs)
    if not crs:
        raise ValueError("layer has no CRS")
    transformer = None
    if not is_geographic(crs):
        try:
            transformer = Transformer.from_crs(crs, DISPLAY_CRS, always_xy=True)
        except CRSError as exc:
            raise ValueError(f"cannot use CRS {crs}") from exc

    def project(x: float, y: float) -> tuple[float, float]:
        # EPSG:4490 and EPSG:4326 are the platform lon/lat exchange.
        if transformer is None:
            return x, y
        lon, lat = transformer.transform(x, y)
        return float(lon), float(lat)

    features: list[dict[str, Any]] = []
    for feature in collection.get("features") or []:
        if not isinstance(feature, dict):
            continue
        geometry = feature.get("geometry")
        if not isinstance(geometry, dict) or "coordinates" not in geometry:
            continue
        props = feature.get("properties")
        if not isinstance(props, dict):
            props = {}
        features.append(
            {
                "type": "Feature",
                "properties": dict(props),
                "geometry": {
                    "type": geometry.get("type"),
                    "coordinates": _transform_coords(geometry.get("coordinates"), project),
                },
            }
        )
    return {"type": "FeatureCollection", "features": features}


def _layer_crs(layer: ProductLayer, product: Product, area: Area | None) -> str:
    meta = layer.metadata_json or {}
    product_meta = product.metadata_json or {}
    return normalize_crs(meta.get("crs") or product_meta.get("crs") or (area.analysis_crs if area else ""))


def _class_code(feature: dict[str, Any]) -> int | None:
    props = feature.get("properties") or {}
    raw = props.get("class_code")
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def load_layer_geojson(layer: ProductLayer, product: Product, area: Area | None) -> dict[str, Any]:
    meta = layer.metadata_json or {}
    doc = _as_feature_collection(meta.get("geojson"))
    if doc is None:
        raise ValueError("layer has no GeoJSON")
    if meta.get("empty") and not doc.get("features"):
        return {"type": "FeatureCollection", "features": []}
    return reproject_geojson(doc, _layer_crs(layer, product, area))


def _features_for(layer: ProductLayer | None, product: Product, area: Area | None) -> list[dict[str, Any]]:
    if layer is None:
        return []
    try:
        collection = load_layer_geojson(layer, product, area)
    except (ValueError, CRSError):
        return []
    return list(collection.get("features") or [])


def _spec(
    layer_key: str,
    title: str,
    kind: str,
    features: list[dict[str, Any]],
    *,
    fill: bool = True,
) -> dict[str, Any]:
    stamped: list[dict[str, Any]] = []
    for feature in features:
        props = dict(feature.get("properties") or {})
        props.setdefault("name", title)
        stamped.append({**feature, "properties": props})
    return {
        "layer_key": layer_key,
        "title": title,
        "kind": kind,
        "fill": fill,
        "geojson": {"type": "FeatureCollection", "features": stamped},
    }


def _impact_layers(by_key: dict[str, ProductLayer], product: Product, area: Area | None) -> list[dict[str, Any]]:
    layers: list[dict[str, Any]] = []
    for key, title, kind, fill in _IMPACT_SPECS:
        features = _features_for(by_key.get(key), product, area)
        if features:
            layers.append(_spec(key, title, kind, features, fill=fill))
    return layers


def display_layers_for(db: Session, product: Product, area: Area | None) -> list[dict[str, Any]]:
    """Vector layers the one-map can draw. Empty flood layers are omitted.

    Without a published baseline the product is extracted water, not 本次淹没.
    Impact objects are included only when this product actually stored them.
    """
    rows = (
        db.query(ProductLayer)
        .filter(ProductLayer.product_id == product.id, ProductLayer.layer_key.in_(_VECTOR_KEYS + _IMPACT_KEYS))
        .all()
    )
    by_key = {row.layer_key: row for row in rows}
    water = _features_for(by_key.get("water_current_poly"), product, area)
    layers: list[dict[str, Any]] = []
    if product.flood_event_status == "computed":
        event = _features_for(by_key.get("flood_event_poly"), product, area)
        if not event:
            event = [feature for feature in water if _class_code(feature) == 3]
        baseline = [feature for feature in water if _class_code(feature) == 2]
        if baseline:
            layers.append(_spec("water_current_poly", "本底水体", "baseline", baseline))
        if event:
            layers.append(_spec("flood_event_poly", "本次淹没", "event", event))
    elif water:
        title = "提取水体（未扣本底）" if product.flood_event_status == "baseline_missing" else "当期水体"
        layers.append(_spec("water_current_poly", title, "water", water))
    layers.extend(_impact_layers(by_key, product, area))
    return layers


def _bbox_collection(bbox: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(bbox, dict):
        return None
    try:
        minx, miny, maxx, maxy = (float(bbox[key]) for key in ("minx", "miny", "maxx", "maxy"))
    except (KeyError, TypeError, ValueError):
        return None
    ring = [[minx, miny], [maxx, miny], [maxx, maxy], [minx, maxy], [minx, miny]]
    return {
        "type": "FeatureCollection",
        "features": [{"type": "Feature", "properties": {}, "geometry": {"type": "Polygon", "coordinates": [ring]}}],
    }


def area_outline(area: Area) -> dict[str, Any] | None:
    """AOI in EPSG:4326, using the area exchange CRS. Not a flood layer."""
    doc = _as_feature_collection(area.aoi_geojson)
    crs = normalize_crs(area.exchange_crs)
    if doc is None:
        doc = _bbox_collection(area.bbox_json)
        if isinstance(area.bbox_json, dict):
            crs = normalize_crs(area.bbox_json.get("crs")) or crs
    if doc is None or not crs:
        return None
    try:
        collection = reproject_geojson(doc, crs)
    except (ValueError, CRSError):
        return None
    for feature in collection["features"]:
        props = feature.setdefault("properties", {})
        props.setdefault("name", area.name)
        props["role"] = "aoi"
    return collection


def _stat_value(row: ImpactStat) -> float:
    try:
        return float(row.value)
    except (TypeError, ValueError):
        return 0.0


def summarize_impact(rows: list[ImpactStat], scope: str = "default") -> dict[str, Any]:
    """Roll up measured cross-stats. Categories with no rows stay absent, not zero-filled."""

    def hits(object_types: set[str], metrics: set[str]) -> list[ImpactStat]:
        return [
            row
            for row in rows
            if row.scope == scope and row.object_type in object_types and row.metric in metrics and _stat_value(row) > 0
        ]

    def unique(found: list[ImpactStat]) -> set[str]:
        return {row.object_id for row in found}

    def total(found: list[ImpactStat], metric: str) -> float:
        return sum(_stat_value(row) for row in found if row.metric == metric)

    roads = hits({"road"}, {"affected_length_m"})
    settlements = hits({"settlement"}, {"affected_area_ha", "affected_area_m2"})
    admins = hits({"admin_county", "admin_township"}, {"affected_area_ha", "affected_area_m2"})
    configured = bool(rows)
    summary: dict[str, Any] = {"impact_configured": configured, "scope": scope}
    if not configured:
        return summary
    summary.update(
        {
            "affected_road_count": len(unique(roads)),
            "affected_road_length_m": int(round(total(roads, "affected_length_m"))),
            "affected_settlement_count": len(unique(settlements)),
            "affected_settlement_area_ha": round(total(settlements, "affected_area_ha"), 2),
            "affected_admin_count": len(unique(admins)),
            "affected_admin_area_ha": round(total(admins, "affected_area_ha"), 2),
        }
    )
    return summary


def emergency_document(db: Session, product: Product) -> dict[str, Any] | None:
    layer = (
        db.query(ProductLayer)
        .filter(ProductLayer.product_id == product.id, ProductLayer.layer_key == "emergency_map")
        .one_or_none()
    )
    if layer is None:
        return None
    doc = (layer.metadata_json or {}).get("document")
    return doc if isinstance(doc, dict) else None


def published_map(
    db: Session,
    *,
    org_id: uuid.UUID,
    area: Area,
    scene_code: str | None = None,
) -> dict[str, Any]:
    """Default one-map payload: this area plus published product vectors only."""
    query = db.query(Product).filter(
        Product.org_id == org_id,
        Product.area_id == area.id,
        Product.deleted_at.is_(None),
        Product.status == "published",
    )
    if scene_code:
        query = query.filter(Product.scene_code == scene_code)
    rows = query.order_by(Product.published_at.desc(), Product.created_at.desc()).all()
    product_ids = [product.id for product in rows]
    stat_rows = (
        db.query(ImpactStat).filter(ImpactStat.product_id.in_(product_ids)).all() if product_ids else []
    )
    by_product: dict[Any, list[ImpactStat]] = {}
    for stat in stat_rows:
        by_product.setdefault(stat.product_id, []).append(stat)
    products: list[dict[str, Any]] = []
    for product in rows:
        cross = [row for row in by_product.get(product.id, []) if row.object_type != "extent"]
        products.append(
            {
                "id": str(product.id),
                "title": product.title,
                "status": product.status,
                "flood_event_status": product.flood_event_status,
                "baseline_version": product.baseline_version or "",
                "baseline_version_id": str(product.baseline_version_id) if product.baseline_version_id else None,
                "version": product.version,
                "scene_code": product.scene_code,
                "extracted_water_ha": product.extracted_water_ha,
                "water_current_ha": product.water_current_ha,
                "flood_event_ha": product.flood_event_ha,
                "acquisition_start": product.acquisition_start.isoformat() if product.acquisition_start else None,
                "s1_product_id": product.s1_product_id,
                "layers": display_layers_for(db, product, area),
                "impact": summarize_impact(cross),
                "impact_including_lowconf": summarize_impact(cross, "including_lowconf"),
                "emergency_map": emergency_document(db, product),
            }
        )
    return {
        "area": {
            "id": str(area.id),
            "name": area.name,
            "analysis_crs": area.analysis_crs,
            "exchange_crs": area.exchange_crs,
            "aoi": area_outline(area),
        },
        "products": products,
    }
