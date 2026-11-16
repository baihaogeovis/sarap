"""Official baseline resolution uses only data_asset_versions.

The legacy /baselines (BaselineAsset) API is kept, but it must not decide
whether a flood product has a baseline or may emit flood_event layers.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.core.responses import APIError
from app.models import Area, DataAsset, DataAssetVersion, Dataset, Product, Task
from app.models.base import utcnow


def get_published_version(db: Session, version_id: uuid.UUID | None) -> DataAssetVersion | None:
    if version_id is None:
        return None
    row = db.get(DataAssetVersion, version_id)
    if row is None or row.deleted_at is not None or row.review_status != "published":
        return None
    return row


def has_published_baseline(db: Session, version_id: uuid.UUID | None) -> bool:
    return get_published_version(db, version_id) is not None


def version_is_referenced(db: Session, version_id: uuid.UUID) -> bool:
    if db.query(Task.id).filter(Task.baseline_version_id == version_id, Task.deleted_at.is_(None)).first():
        return True
    if db.query(Product.id).filter(Product.baseline_version_id == version_id, Product.deleted_at.is_(None)).first():
        return True
    return False


def _preferred_version_id(config: dict[str, Any] | None) -> uuid.UUID | None:
    raw = ((config or {}).get("baselines") or {}).get("preferred_version_id")
    if not raw:
        return None
    try:
        return uuid.UUID(str(raw))
    except ValueError as exc:
        raise APIError(409, "BASELINE_VERSION_CONFLICT", "preferred_version_id 不是合法 UUID") from exc


def _configured_asset_id(config: dict[str, Any] | None, key: str = "permanent_water_asset_id") -> uuid.UUID | None:
    raw = ((config or {}).get("baselines") or {}).get(key)
    if not raw:
        return None
    try:
        return uuid.UUID(str(raw))
    except ValueError:
        return None


def _as_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _load_geojson(data: dict[str, Any] | None):
    """Parse a GeoJSON geometry / Feature / FeatureCollection. Returns None if unusable."""
    if not data or not isinstance(data, dict):
        return None
    try:
        from shapely.geometry import shape
        from shapely.ops import unary_union

        typ = data.get("type")
        if typ == "Feature":
            geometry = data.get("geometry")
            if not geometry:
                return None
            geom = shape(geometry)
        elif typ == "FeatureCollection":
            geoms = [
                shape(feat["geometry"])
                for feat in (data.get("features") or [])
                if isinstance(feat, dict) and feat.get("geometry")
            ]
            if not geoms:
                return None
            geom = unary_union(geoms)
        else:
            geom = shape(data)
        if geom is None or geom.is_empty:
            return None
        return geom
    except (TypeError, ValueError, AttributeError, KeyError):
        return None


def _covers_time(version: DataAssetVersion, when: datetime | None) -> bool:
    """valid_from inclusive, valid_to exclusive. A null bound means unrestricted.

    If an imaging instant is provided it must fall in the window. If it is missing
    and a window exists, evaluate against now so expired / not-yet-valid versions
    are not treated as always applicable.
    """
    start = _as_utc(version.valid_from)
    end = _as_utc(version.valid_to)
    if start is None and end is None:
        return True
    instant = _as_utc(when) or utcnow()
    if start is not None and instant < start:
        return False
    if end is not None and instant >= end:
        return False
    return True


DEFAULT_EXCHANGE_CRS = "EPSG:4490"
# Lon/lat exchange CRSs are treated as one family for covers (no reprojection).
# They must never be compared directly with a projected CRS such as EPSG:4548.
_GEOGRAPHIC_EXCHANGE_CRS = {"EPSG:4490", "EPSG:4326"}


def _exchange_crs(area: Area | None) -> str:
    raw = (area.exchange_crs if area is not None else None) or DEFAULT_EXCHANGE_CRS
    return canonicalize_crs(raw) or DEFAULT_EXCHANGE_CRS


def canonicalize_crs(raw: str | None) -> str | None:
    """Normalize CRS identifiers to EPSG:xxxx / EPSG:4326 (for CRS84)."""
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    upper = text.upper().replace(" ", "")
    if "CRS84" in upper or "CRS:84" in upper:
        return "EPSG:4326"
    # urn:ogc:def:crs:EPSG::4490  or  urn:ogc:def:crs:EPSG:6.9:4490  or  EPSG:4490
    marker = "EPSG"
    if marker in upper:
        tail = upper[upper.rfind(marker) + len(marker) :].lstrip(":").lstrip("_")
        # skip optional version "6.9:" in URN
        if "." in tail and ":" in tail:
            tail = tail.split(":", 1)[-1]
        digits = "".join(ch for ch in tail if ch.isdigit())
        if digits:
            return f"EPSG:{int(digits)}"
    if upper.isdigit():
        return f"EPSG:{int(upper)}"
    return upper


def _crs_member(data: dict[str, Any] | None) -> str | None:
    if not data or not isinstance(data, dict):
        return None
    raw = data.get("crs")
    if raw is None and isinstance(data.get("properties"), dict):
        raw = data["properties"].get("crs") or data["properties"].get("srs")
    if raw is None:
        return None
    if isinstance(raw, str):
        return canonicalize_crs(raw)
    if isinstance(raw, dict):
        props = raw.get("properties") or {}
        typ = str(raw.get("type") or "")
        if typ.lower() == "epsg" and props.get("code") is not None:
            return canonicalize_crs(f"EPSG:{props['code']}")
        name = props.get("name") or props.get("code") or raw.get("name")
        return canonicalize_crs(str(name) if name is not None else None)
    return None


def extract_geojson_crs(data: dict[str, Any] | None) -> str | None:
    """Return a declared CRS if the GeoJSON (or a nested Feature) carries one."""
    found = _crs_member(data)
    if found:
        return found
    if not data or not isinstance(data, dict):
        return None
    typ = data.get("type")
    if typ == "Feature":
        geom = data.get("geometry")
        return _crs_member(geom) if isinstance(geom, dict) else None
    if typ == "FeatureCollection":
        for feat in data.get("features") or []:
            if isinstance(feat, dict):
                found = extract_geojson_crs(feat)
                if found:
                    return found
    return None


def _effective_crs(data: dict[str, Any] | None, exchange_crs: str) -> str:
    """Declared CRS, or the area exchange_crs (default EPSG:4490) when unmarked.

    Unmarked GeoJSON is never interpreted as analysis_crs / Gauss-Kruger.
    """
    declared = extract_geojson_crs(data)
    if declared:
        return declared
    return canonicalize_crs(exchange_crs) or DEFAULT_EXCHANGE_CRS


def _crs_compatible(left: str, right: str) -> bool:
    if left == right:
        return True
    return left in _GEOGRAPHIC_EXCHANGE_CRS and right in _GEOGRAPHIC_EXCHANGE_CRS


def _looks_projected(geom) -> bool:
    minx, miny, maxx, maxy = geom.bounds
    return max(abs(minx), abs(maxx)) > 180.0 or max(abs(miny), abs(maxy)) > 90.0


def _looks_geographic(geom) -> bool:
    minx, miny, maxx, maxy = geom.bounds
    return max(abs(minx), abs(maxx)) <= 180.0 and max(abs(miny), abs(maxy)) <= 90.0


def _raise_crs_mismatch(left: str, right: str, exchange_crs: str) -> None:
    raise APIError(
        409,
        "BASELINE_CRS_MISMATCH",
        "本底 applicable_area_geojson 与区域 aoi_geojson 坐标系不一致"
        f"（{left} vs {right}）。请都对齐到区域 exchange_crs（{exchange_crs}，默认 EPSG:4490）后再提交。"
        "校验不会静默重投影，也不会把高斯克吕格米制坐标与经纬度直接做 covers。",
    )


def crs_mismatch_pair(
    baseline_geojson: dict[str, Any] | None,
    baseline_geom,
    aoi_geojson: dict[str, Any] | None,
    aoi_geom,
    exchange_crs: str,
) -> tuple[str, str] | None:
    """Return (baseline_crs, aoi_crs) if they are not comparable; else None. Never reprojects."""
    left = _effective_crs(baseline_geojson, exchange_crs)
    right = _effective_crs(aoi_geojson, exchange_crs)
    if not _crs_compatible(left, right):
        return left, right
    # Unmarked GeoJSON is assumed to be exchange_crs; if the coordinates clearly
    # belong to a different kind (metres vs degrees), that is also a mismatch.
    if _looks_projected(baseline_geom) and _looks_geographic(aoi_geom):
        return left, right
    if _looks_geographic(baseline_geom) and _looks_projected(aoi_geom):
        return left, right
    return None


def ensure_same_crs(
    baseline_geojson: dict[str, Any] | None,
    baseline_geom,
    aoi_geojson: dict[str, Any] | None,
    aoi_geom,
    exchange_crs: str,
) -> None:
    """Fail loudly if the two geometries are not in the same CRS. Never reproject."""
    pair = crs_mismatch_pair(baseline_geojson, baseline_geom, aoi_geojson, aoi_geom, exchange_crs)
    if pair is not None:
        _raise_crs_mismatch(pair[0], pair[1], exchange_crs)


# Spatial evaluation outcomes used by auto-filter vs explicit/preferred checks.
SPATIAL_MATCH = "match"
SPATIAL_NOT_APPLICABLE = "not_applicable"
SPATIAL_CRS_MISMATCH = "crs_mismatch"


def _area_id_or_name_conflict(version: DataAssetVersion, asset: DataAsset, area: Area) -> bool:
    """Signals the version is clearly about a different area, without running covers."""
    if asset.area_id is not None and asset.area_id != area.id:
        return True
    name = (version.applicable_area_name or "").strip()
    if name and name not in {area.code, area.name}:
        return True
    return False


def _spatial_status(
    version: DataAssetVersion, asset: DataAsset, area: Area | None
) -> tuple[str, tuple[str, str, str] | None]:
    """Return (status, optional CRS mismatch details).

    Details are (baseline_crs, aoi_crs, exchange_crs) when status is CRS mismatch.
    This never raises and never covers across mismatched CRS.
    """
    if area is None:
        return SPATIAL_NOT_APPLICABLE, None
    if version.applicable_area_geojson:
        applicable = _load_geojson(version.applicable_area_geojson)
        if applicable is None:
            return SPATIAL_NOT_APPLICABLE, None
        aoi = _load_geojson(area.aoi_geojson)
        if aoi is None:
            # AOI not entered yet: do not 409; fall back to area_id.
            if asset.area_id is not None and asset.area_id == area.id:
                return SPATIAL_MATCH, None
            return SPATIAL_NOT_APPLICABLE, None
        exchange = _exchange_crs(area)
        pair = crs_mismatch_pair(
            version.applicable_area_geojson,
            applicable,
            area.aoi_geojson,
            aoi,
            exchange,
        )
        if pair is not None:
            return SPATIAL_CRS_MISMATCH, (pair[0], pair[1], exchange)
        try:
            if bool(applicable.covers(aoi)):
                return SPATIAL_MATCH, None
        except Exception:
            return SPATIAL_NOT_APPLICABLE, None
        return SPATIAL_NOT_APPLICABLE, None
    if asset.area_id is not None and asset.area_id == area.id:
        return SPATIAL_MATCH, None
    name = (version.applicable_area_name or "").strip()
    if name and name in {area.code, area.name}:
        return SPATIAL_MATCH, None
    return SPATIAL_NOT_APPLICABLE, None


def _covers_area(version: DataAssetVersion, asset: DataAsset, area: Area | None) -> bool:
    """Spatial applicability for explicit / preferred ids. CRS mismatch raises 409."""
    status, details = _spatial_status(version, asset, area)
    if status == SPATIAL_CRS_MISMATCH:
        left, right, exchange = details or ("", "", _exchange_crs(area))
        _raise_crs_mismatch(left, right, exchange)
    return status == SPATIAL_MATCH


def require_applicable_version(
    db: Session,
    version_id: uuid.UUID,
    *,
    org_id: uuid.UUID,
    area: Area | None,
    acquired_at: datetime | None,
) -> DataAssetVersion:
    """Validate an explicit baseline_version_id. Never silently substitute another version."""
    row = db.get(DataAssetVersion, version_id)
    if (
        row is None
        or row.deleted_at is not None
        or row.org_id != org_id
        or row.review_status != "published"
    ):
        raise APIError(
            409,
            "BASELINE_NOT_PUBLISHED",
            "baseline_version_id 必须指向 review_status=published 的 data_asset_versions 记录",
        )
    if not _covers_time(row, acquired_at):
        raise APIError(
            409,
            "BASELINE_NOT_IN_VALIDITY_PERIOD",
            "成像时间（acquisition_start，缺省则 data_ready_at）不在本底版本 valid_from（含）/valid_to（不含）内",
        )
    asset = db.get(DataAsset, row.asset_id)
    if asset is None or asset.deleted_at is not None or asset.org_id != org_id:
        raise APIError(
            409,
            "BASELINE_NOT_PUBLISHED",
            "baseline_version_id 对应的本底资产不可用",
        )
    if not _covers_area(row, asset, area):
        raise APIError(
            409,
            "BASELINE_AREA_NOT_APPLICABLE",
            "本底版本不适用该任务区域：有 AOI 时 applicable_area_geojson 必须包含该 AOI；"
            "区域尚未录入 AOI 时回退到 asset.area_id == task.area_id；"
            "无几何时需 area_id 一致，或 applicable_area_name 与区域 name/code 相等",
        )
    return row


def find_matching_published_versions(
    db: Session,
    *,
    org_id: uuid.UUID,
    area: Area | None,
    project_id: uuid.UUID | None,
    acquired_at: datetime | None,
    asset_id: uuid.UUID | None = None,
    asset_type: str = "permanent_water",
) -> tuple[list[DataAssetVersion], list[tuple[str, str, str]]]:
    """Return (matching versions, CRS-mismatch details for otherwise-applicable skips)."""
    q = (
        db.query(DataAssetVersion)
        .join(DataAsset, DataAsset.id == DataAssetVersion.asset_id)
        .filter(
            DataAsset.org_id == org_id,
            DataAsset.status == "active",
            DataAsset.deleted_at.is_(None),
            DataAssetVersion.review_status == "published",
            DataAssetVersion.deleted_at.is_(None),
        )
    )
    if asset_id is not None:
        q = q.filter(DataAsset.id == asset_id)
    else:
        q = q.filter(DataAsset.asset_type == asset_type)
    if project_id is not None:
        q = q.filter((DataAsset.project_id == project_id) | (DataAsset.project_id.is_(None)))
    rows: list[DataAssetVersion] = []
    crs_blocked: list[tuple[str, str, str]] = []
    for version in q.all():
        asset = db.get(DataAsset, version.asset_id)
        if asset is None:
            continue
        if not _covers_time(version, acquired_at):
            continue
        status, details = _spatial_status(version, asset, area)
        if status == SPATIAL_MATCH:
            rows.append(version)
            continue
        if status == SPATIAL_CRS_MISMATCH:
            # Skip during auto-filter. Only remember mismatches that would otherwise
            # have been spatial candidates for this area (not an unrelated version).
            if area is not None and not _area_id_or_name_conflict(version, asset, area):
                if details is not None:
                    crs_blocked.append(details)
            continue
    return rows, crs_blocked


def resolve_baseline_version(
    db: Session,
    *,
    org_id: uuid.UUID,
    area: Area | None,
    project_id: uuid.UUID | None,
    acquired_at: datetime | None,
    config: dict[str, Any] | None,
    explicit_version_id: uuid.UUID | None = None,
    required: bool = False,
) -> DataAssetVersion | None:
    """Pick the unique published data_asset_version for 本次淹没, or fail.

    No baseline at all is allowed (P0). Multiple published matches without a
    usable preferred_version_id raise BASELINE_VERSION_CONFLICT.
    """
    if explicit_version_id is not None:
        return require_applicable_version(
            db,
            explicit_version_id,
            org_id=org_id,
            area=area,
            acquired_at=acquired_at,
        )

    config = config or (area.config_json if area is not None else {}) or {}
    asset_id = _configured_asset_id(config)
    candidates, crs_blocked = find_matching_published_versions(
        db,
        org_id=org_id,
        area=area,
        project_id=project_id,
        acquired_at=acquired_at,
        asset_id=asset_id,
    )
    # preferred is checked before auto-binding a unique candidate, so a
    # preferred id that fails CRS / validity / area still 409s and is not swapped.
    preferred = _preferred_version_id(config)
    if preferred is not None:
        for version in candidates:
            if version.id == preferred:
                return version
        require_applicable_version(
            db, preferred, org_id=org_id, area=area, acquired_at=acquired_at
        )
        raise APIError(
            409,
            "BASELINE_VERSION_CONFLICT",
            "config_json.baselines.preferred_version_id 不是当前区域、成像时刻下可用的已发布版本，禁止静默任选",
        )
    if not candidates:
        # Auto-resolve: only 409 CRS if a version was skipped solely for CRS
        # (time and area identity otherwise ok). Unrelated messy-CRS versions
        # must not block P0 "no baseline".
        if crs_blocked:
            left, right, exchange = crs_blocked[0]
            _raise_crs_mismatch(left, right, exchange)
        if required:
            raise APIError(400, "baseline_required", "未找到已发布且适用的常年水体本底版本")
        return None
    if len(candidates) == 1:
        return candidates[0]
    raise APIError(
        409,
        "BASELINE_VERSION_CONFLICT",
        "同一资产在同一区域、同一成像时刻存在多个已发布版本，请在区域 config_json.baselines.preferred_version_id 中指定唯一版本，禁止静默任选",
    )


def dataset_imagery_fields(dataset: Dataset | None) -> tuple[datetime | None, datetime | None, str]:
    """Map a catalog Dataset to acquisition window and Sentinel-1 PRODUCT-ID.

    Dataset.time_start/time_end → acquisition_start/acquisition_end.
    Dataset.s1_product_id (or metadata_json.s1_product_id / code starting with S1) → s1_product_id.
    This is distinct from Task/Product.scene_id, which is the platform scene (e.g. flood).
    """
    if dataset is None:
        return None, None, ""
    meta = dataset.metadata_json or {}
    s1 = (dataset.s1_product_id or "").strip() or str(meta.get("s1_product_id") or meta.get("product_id") or "").strip()
    if not s1 and dataset.code.upper().startswith("S1"):
        s1 = dataset.code
    return dataset.time_start, dataset.time_end, s1


def fill_imagery_fields(
    target: Task | Product,
    *,
    dataset: Dataset | None = None,
    acquisition_start: datetime | None = None,
    acquisition_end: datetime | None = None,
    s1_product_id: str | None = None,
) -> None:
    ds_start, ds_end, ds_s1 = dataset_imagery_fields(dataset)
    if getattr(target, "acquisition_start", None) is None:
        target.acquisition_start = acquisition_start or ds_start
    if getattr(target, "acquisition_end", None) is None:
        target.acquisition_end = acquisition_end or ds_end
    if not getattr(target, "s1_product_id", ""):
        target.s1_product_id = (s1_product_id or ds_s1 or "") if (s1_product_id or ds_s1) else ""


def compute_idempotency_key(
    *,
    scene_id: uuid.UUID | str | None,
    area_id: uuid.UUID | None,
    s1_product_id: str | None,
    baseline_version_id: uuid.UUID | None,
    algo_profile_id: str | None,
    params: dict[str, Any] | None,
) -> str:
    """Platform auto key, aligned with the engine: (scene_id, area_id, s1_product_id,
    baseline_version_id, algo_profile_id, param_hash).

    scene_id is the platform scene UUID (same field as the engine dispatch payload),
    not a Sentinel-1 PRODUCT-ID and not scene_code.
    """
    payload = json.dumps(params or {}, sort_keys=True, default=str, separators=(",", ":"))
    param_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
    return "|".join(
        [
            str(scene_id or ""),
            str(area_id or ""),
            s1_product_id or "",
            str(baseline_version_id or ""),
            algo_profile_id or "",
            param_hash,
        ]
    )


def suggest_analysis_crs(lon: float) -> str:
    """CGCS2000 3° Gauss-Kruger belt from a geographic longitude.

    EPSG:4548 (CM 117E) is only an example default for AOIs near 116°E, not a national default.
    New areas must pick the belt of their central meridian: EPSG = 4534 + (CM-75)/3, CM = 3*round(lon/3).
    """
    cm = int(round(lon / 3.0) * 3)
    cm = max(75, min(135, cm))
    return f"EPSG:{4534 + (cm - 75) // 3}"


def centroid_lon(aoi_geojson: dict[str, Any] | None, bbox_json: dict[str, Any] | None) -> float | None:
    if bbox_json:
        if "minx" in bbox_json and "maxx" in bbox_json:
            return (float(bbox_json["minx"]) + float(bbox_json["maxx"])) / 2.0
        if "west" in bbox_json and "east" in bbox_json:
            return (float(bbox_json["west"]) + float(bbox_json["east"])) / 2.0
    if not aoi_geojson:
        return None
    coords = aoi_geojson.get("coordinates")
    if not coords:
        return None
    xs: list[float] = []

    def _walk(node: Any) -> None:
        if isinstance(node, (list, tuple)) and node and isinstance(node[0], (int, float)):
            xs.append(float(node[0]))
        elif isinstance(node, (list, tuple)):
            for item in node:
                _walk(item)

    _walk(coords)
    if not xs:
        return None
    return sum(xs) / len(xs)
