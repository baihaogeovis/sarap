from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.core.deps import Principal
from app.core.responses import APIError
from app.models import ImpactStat, Product, ProductLayer
from app.models.base import utcnow
from app.services import audit
from app.services.baselines import has_published_baseline

# P0 short publish: draft -> published is allowed (duty_officer and admin).
# pending_qc is kept for P1 full QC. Reject returns to draft, never withdrawn.
TRANSITIONS: dict[tuple[str, str], str] = {
    ("draft", "submit"): "pending_qc",
    ("draft", "publish"): "published",
    ("pending_qc", "reject"): "draft",
    ("pending_qc", "publish"): "published",
    ("published", "withdraw"): "withdrawn",
}

REQUIRED_PERM = {
    "submit": "product.submit",
    "reject": "product.qc",
    "publish": "product.publish",
    "withdraw": "product.withdraw",
}

IMMUTABLE_STATUSES = {"published", "withdrawn"}

HARD_ERROR_CODES = {"PROCESSING_FAILED", "GRID_MISALIGNED", "COVERAGE_TOO_LOW"}

EXTRACTED_WATER_LABEL = "提取水体面积（未扣本底）"
WATER_CURRENT_LABEL = "当期水体面积"
FLOOD_EVENT_LABEL = "本次淹没面积"

P0_LAYER_KEYS = [
    "class_map",
    "water_current",
    "water_current_poly",
    "qc_flags",
    "qc_summary",
    "metadata",
]
BASELINE_LAYER_KEYS = ["flood_event", "flood_event_poly"]

DEPTH_KEY_FRAGMENTS = ("depth", "water_depth", "flood_depth")


def has_baseline(db: Session, product: Product) -> bool:
    """True only when baseline_version_id points at a published data_asset_version.

    Legacy BaselineAsset / baseline_version strings are ignored.
    """
    return has_published_baseline(db, product.baseline_version_id)


def is_flood_product(product: Product) -> bool:
    return product.scene_code == "flood" or product.product_type.upper().startswith("SARAP_FLOOD")


def flood_event_status_for(db: Session, product: Product, *, has_result: bool = True) -> str:
    if not is_flood_product(product) or not has_result:
        return "none"
    return "computed" if has_baseline(db, product) else "baseline_missing"


def layer_keys_for(db: Session, product: Product) -> list[str]:
    keys = list(P0_LAYER_KEYS)
    if has_baseline(db, product):
        keys.extend(BASELINE_LAYER_KEYS)
    return keys


def round_ha(value: float | None) -> float | None:
    if value is None:
        return None
    return round(float(value), 2)


def _area_pair(metric_prefix: str, label: str, ha_value: float) -> list[dict[str, Any]]:
    ha = round_ha(ha_value)
    m2 = int(round(ha * 10_000))
    return [
        {"metric": f"{metric_prefix}_ha", "label": label, "value": ha, "unit": "ha"},
        {"metric": f"{metric_prefix}_m2", "label": f"{label}（平方米）", "value": m2, "unit": "m2"},
    ]


def area_metric_rows(db: Session, product: Product) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if has_baseline(db, product):
        if product.water_current_ha is not None:
            rows.extend(_area_pair("water_current", WATER_CURRENT_LABEL, product.water_current_ha))
        if product.flood_event_ha is not None:
            rows.extend(_area_pair("flood_event", FLOOD_EVENT_LABEL, product.flood_event_ha))
    else:
        if product.extracted_water_ha is not None:
            rows.extend(_area_pair("extracted_water", EXTRACTED_WATER_LABEL, product.extracted_water_ha))
    return rows


def transition(
    db: Session,
    product: Product,
    action: str,
    principal: Principal,
    *,
    comment: str = "",
    reason: str = "",
) -> Product:
    principal.require(REQUIRED_PERM[action])
    if action == "publish" and product.re_qc_required and product.status == "draft":
        raise APIError(
            409,
            "re_qc_required",
            "撤回后的新版本必须重新质检，不能走 P0 最短发布",
        )
    if action == "reject":
        why = (reason or comment).strip()
        if not why:
            raise APIError(422, "validation_error", "质检打回必须填写原因")
        reason = why
    key = (product.status, action)
    if key not in TRANSITIONS:
        raise APIError(
            409,
            "invalid_transition",
            f"Cannot {action} a product in status {product.status}",
        )
    before = {"status": product.status, "version": product.version}
    product.status = TRANSITIONS[key]
    now = utcnow()
    if action == "submit":
        if product.submitted_at is None:
            product.submitted_at = now
        product.re_qc_required = False
    elif action == "reject":
        # P1: return to draft with a required reason. Never use withdrawn for a QC reject.
        product.reviewed_by = principal.id if principal.typ == "user" else product.reviewed_by
        product.reviewed_at = now
        product.review_comment = comment or reason
        product.reject_reason = reason
    elif action == "publish":
        product.reviewed_by = principal.id if principal.typ == "user" else product.reviewed_by
        product.reviewed_at = now
        product.published_at = now
        if comment:
            product.review_comment = comment
        product.re_qc_required = False
    elif action == "withdraw":
        product.withdrawn_at = now
        product.withdraw_reason = reason or comment
    audit.record(
        db,
        actor_type=principal.typ,
        actor_id=principal.id,
        action=f"product.{action}",
        resource_type="product",
        resource_id=str(product.id),
        org_id=principal.org_id,
        project_id=product.project_id,
        before=before,
        after={"status": product.status, "version": product.version},
    )
    db.add(product)
    db.flush()
    return product


def assert_mutable(product: Product) -> None:
    if product.status in IMMUTABLE_STATUSES:
        raise APIError(
            409,
            "immutable_product",
            "已发布或已撤回的产品禁止就地修改；撤回后须新建版本并重新质检",
        )


def new_version(db: Session, product: Product, principal: Principal) -> Product:
    principal.require("product.draft")
    if product.status != "withdrawn":
        raise APIError(
            409,
            "invalid_transition",
            "A new version can only be created from a withdrawn product",
        )
    clone = Product(
        org_id=product.org_id,
        project_id=product.project_id,
        area_id=product.area_id,
        scene_id=product.scene_id,
        scene_code=product.scene_code,
        task_id=product.task_id,
        imagery_dataset_id=product.imagery_dataset_id,
        baseline_asset_id=product.baseline_asset_id,
        data_asset_id=product.data_asset_id,
        baseline_version=product.baseline_version,
        baseline_version_id=product.baseline_version_id,
        engine_name=product.engine_name,
        engine_params_json=dict(product.engine_params_json or {}),
        code=product.code,
        title=product.title,
        product_type=product.product_type,
        version=product.version + 1,
        status="draft",
        storage_uri=product.storage_uri,
        artifacts_json=list(product.artifacts_json or []),
        metadata_json=dict(product.metadata_json or {}),
        flood_event_status=product.flood_event_status,
        extracted_water_ha=product.extracted_water_ha,
        water_current_ha=product.water_current_ha,
        flood_event_ha=product.flood_event_ha,
        lowconf_ha=product.lowconf_ha,
        suggested_target_minutes=product.suggested_target_minutes,
        data_ready_at=product.data_ready_at,
        processed_at=product.processed_at,
        re_qc_required=True,
        supersedes_id=product.id,
        acquisition_start=product.acquisition_start,
        acquisition_end=product.acquisition_end,
        s1_product_id=product.s1_product_id,
    )
    db.add(clone)
    db.flush()
    # Copy layers and P0 area stats onto the new draft. Cross-stats stay with the old row.
    for layer in db.query(ProductLayer).filter(ProductLayer.product_id == product.id).all():
        db.add(
            ProductLayer(
                org_id=layer.org_id,
                product_id=clone.id,
                layer_key=layer.layer_key,
                media_type=layer.media_type,
                storage_uri=layer.storage_uri,
                metadata_json=dict(layer.metadata_json or {}),
            )
        )
    for stat in (
        db.query(ImpactStat)
        .filter(ImpactStat.product_id == product.id, ImpactStat.object_type == "extent")
        .all()
    ):
        db.add(
            ImpactStat(
                org_id=stat.org_id,
                product_id=clone.id,
                object_type=stat.object_type,
                object_id=stat.object_id,
                object_name=stat.object_name,
                metric=stat.metric,
                value=stat.value,
                unit=stat.unit,
                scope=stat.scope,
                extra_json=dict(stat.extra_json or {}),
            )
        )
    audit.record(
        db,
        actor_type=principal.typ,
        actor_id=principal.id,
        action="product.new_version",
        resource_type="product",
        resource_id=str(clone.id),
        org_id=principal.org_id,
        project_id=product.project_id,
        before={"id": str(product.id), "version": product.version, "status": product.status},
        after={"id": str(clone.id), "version": clone.version, "status": clone.status, "re_qc_required": True},
    )
    return clone


def visible_status_filter(principal: Principal) -> list[str] | None:
    """Readonly (and default one-map) only see published. Withdrawn is hidden from them."""
    if "admin" in principal.roles or "duty_officer" in principal.roles:
        return None
    if principal.has("product.publish") or principal.has("product.qc"):
        return None
    return ["published"]


def to_meta_safe(metadata: dict[str, Any] | None) -> dict[str, Any]:
    """Drop depth fields and expose suggested_target_minutes instead of a committed SLA."""
    data = dict(metadata or {})
    for key in list(data):
        lowered = key.lower()
        if any(frag in lowered for frag in DEPTH_KEY_FRAGMENTS):
            data.pop(key, None)
    if "sla_minutes" in data and "suggested_target_minutes" not in data:
        data["suggested_target_minutes"] = data.pop("sla_minutes")
    else:
        data.pop("sla_minutes", None)
    return data


def reject_depth_fields(metadata: dict[str, Any] | None) -> None:
    data = metadata or {}
    bad = [key for key in data if any(frag in key.lower() for frag in DEPTH_KEY_FRAGMENTS)]
    if bad:
        raise APIError(422, "validation_error", f"水深相关字段被禁止: {', '.join(bad)}")


def sync_layers(db: Session, product: Product, artifacts: list[Any] | None = None) -> None:
    """Materialize product_layers from artifacts, filtered by whether a baseline was used."""
    allowed = set(layer_keys_for(db, product))
    incoming: dict[str, dict[str, Any]] = {}
    for item in artifacts or product.artifacts_json or []:
        if not isinstance(item, dict):
            continue
        key = item.get("layer_key") or item.get("name") or item.get("key")
        if not key:
            continue
        incoming[str(key)] = item
    # Official list: omit flood_event* when there is no baseline (or keep empty + status).
    for key, item in incoming.items():
        if key in BASELINE_LAYER_KEYS and not has_baseline(db, product):
            continue
        if key not in allowed and key not in {"thematic_map", "sigma0_vv_db", "impact_stats", "qc_summary"}:
            # still store unknown non-event layers for archival
            pass
        existing = (
            db.query(ProductLayer)
            .filter(ProductLayer.product_id == product.id, ProductLayer.layer_key == key)
            .one_or_none()
        )
        meta = dict(item.get("metadata_json") or item.get("metadata") or {})
        if existing is None:
            db.add(
                ProductLayer(
                    org_id=product.org_id,
                    product_id=product.id,
                    layer_key=key,
                    media_type=str(item.get("media_type") or "application/octet-stream"),
                    storage_uri=str(item.get("storage_uri") or item.get("uri") or ""),
                    metadata_json=meta,
                )
            )
        else:
            existing.media_type = str(item.get("media_type") or existing.media_type)
            existing.storage_uri = str(item.get("storage_uri") or item.get("uri") or existing.storage_uri)
            existing.metadata_json = meta or existing.metadata_json
    db.flush()


def sync_area_stats(db: Session, product: Product) -> None:
    db.query(ImpactStat).filter(
        ImpactStat.product_id == product.id, ImpactStat.object_type == "extent"
    ).delete()
    baseline_id = str(product.baseline_version_id) if has_baseline(db, product) else None
    for row in area_metric_rows(db, product):
        db.add(
            ImpactStat(
                org_id=product.org_id,
                product_id=product.id,
                object_type="extent",
                object_id=str(product.area_id or ""),
                object_name=row["label"],
                metric=row["metric"],
                value=float(row["value"]),
                unit=row["unit"],
                scope="default",
                extra_json={
                    "label": row["label"],
                    "parent_admin_code": "",
                    "baseline_version_id": baseline_id,
                },
            )
        )
    db.flush()


def official_stat_extra(product: Product, extra: dict[str, Any] | None, db: Session | None = None) -> dict[str, Any]:
    """Lock ImpactStat extra_json keys used by GIS (parent_admin_code, baseline_version_id)."""
    data = dict(extra or {})
    data.setdefault("parent_admin_code", data.get("parent_admin_code") or "")
    if "baseline_version_id" not in data:
        data["baseline_version_id"] = (
            str(product.baseline_version_id)
            if product.baseline_version_id and (db is None or has_baseline(db, product))
            else None
        )
    return data
