from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.v1.serializers import product_out
from app.core.db import get_db
from app.core.deps import Principal, get_current_principal
from app.core.responses import APIError, ok
from app.models import Area, Dataset, ImpactStat, Product, ProductLayer, Project, Scene, Task
from app.schemas.common import ImpactStatOut, ProductIn, ProductLayerOut, TransitionIn
from app.services import product as product_service
from app.services.baselines import fill_imagery_fields, require_applicable_version

router = APIRouter(prefix="/products", tags=["products"])


def _get(db: Session, product_id: uuid.UUID, org_id: uuid.UUID) -> Product:
    row = db.get(Product, product_id)
    if row is None or row.org_id != org_id or row.deleted_at is not None:
        raise APIError(404, "not_found", "Product not found")
    return row


@router.get("")
def list_products(
    project_id: uuid.UUID | None = Query(default=None),
    area_id: uuid.UUID | None = Query(default=None),
    for_map: bool = Query(default=False, description="Default one-map: published only, never withdrawn"),
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    principal.require("product.read")
    q = db.query(Product).filter(Product.org_id == principal.org_id, Product.deleted_at.is_(None))
    if project_id:
        q = q.filter(Product.project_id == project_id)
    if area_id:
        q = q.filter(Product.area_id == area_id)
    if for_map:
        q = q.filter(Product.status == "published")
    else:
        allowed = product_service.visible_status_filter(principal)
        if allowed is not None:
            q = q.filter(Product.status.in_(allowed))
    rows = q.order_by(Product.created_at.desc()).all()
    return ok([product_out(r).model_dump(mode="json") for r in rows], meta={"total": len(rows)})


@router.post("")
def create_product(
    body: ProductIn,
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    principal.require("product.draft")
    project = db.get(Project, body.project_id)
    if project is None or project.org_id != principal.org_id:
        raise APIError(404, "not_found", "Project not found")
    scene = None
    if body.scene_code:
        scene = db.query(Scene).filter(Scene.code == body.scene_code).one_or_none()
    product_service.reject_depth_fields(body.metadata_json)
    metadata = product_service.to_meta_safe(body.metadata_json)
    # Official baseline is only a published, applicable data_asset_version.
    # Ignore legacy baseline_version / baseline_asset_id.
    area = db.get(Area, body.area_id) if body.area_id else None
    if body.task_id:
        task_for_area = db.get(Task, body.task_id)
        if task_for_area is not None and area is None and task_for_area.area_id is not None:
            area = db.get(Area, task_for_area.area_id)
    acquired_at = body.acquisition_start or body.data_ready_at
    if acquired_at is None and body.task_id:
        task_for_time = db.get(Task, body.task_id)
        if task_for_time is not None:
            acquired_at = task_for_time.acquisition_start or task_for_time.data_ready_at
    published = (
        require_applicable_version(
            db,
            body.baseline_version_id,
            org_id=principal.org_id,
            area=area,
            acquired_at=acquired_at,
        )
        if body.baseline_version_id
        else None
    )
    has_base = published is not None
    official_version_id = published.id if published else None
    official_asset_id = published.asset_id if published else body.data_asset_id
    row = Product(
        org_id=principal.org_id,
        project_id=body.project_id,
        area_id=body.area_id,
        scene_id=scene.id if scene else None,
        scene_code=body.scene_code,
        task_id=body.task_id,
        imagery_dataset_id=body.imagery_dataset_id,
        baseline_asset_id=body.baseline_asset_id,
        data_asset_id=official_asset_id,
        baseline_version=published.version_no if published else "",
        baseline_version_id=official_version_id,
        engine_name=body.engine_name,
        engine_params_json=body.engine_params_json,
        code=body.code or f"P-{uuid.uuid4().hex[:10]}",
        title=body.title,
        product_type=body.product_type,
        version=1,
        status="draft",
        storage_uri=body.storage_uri,
        artifacts_json=body.artifacts_json,
        metadata_json=metadata,
        flood_event_status="none",
        extracted_water_ha=None if has_base else product_service.round_ha(body.extracted_water_ha),
        water_current_ha=product_service.round_ha(body.water_current_ha) if has_base else None,
        flood_event_ha=product_service.round_ha(body.flood_event_ha) if has_base else None,
        lowconf_ha=product_service.round_ha(body.lowconf_ha),
        suggested_target_minutes=body.suggested_target_minutes or 240,
        data_ready_at=body.data_ready_at,
        processed_at=body.processed_at,
        acquisition_start=body.acquisition_start,
        acquisition_end=body.acquisition_end,
        s1_product_id=body.s1_product_id or "",
    )
    if body.task_id:
        task = db.get(Task, body.task_id)
        if task is not None:
            if row.area_id is None:
                row.area_id = task.area_id
            fill_imagery_fields(row, acquisition_start=task.acquisition_start, acquisition_end=task.acquisition_end, s1_product_id=task.s1_product_id)
            if row.data_ready_at is None:
                row.data_ready_at = task.data_ready_at
    if body.imagery_dataset_id:
        fill_imagery_fields(row, dataset=db.get(Dataset, body.imagery_dataset_id))
    row.flood_event_status = product_service.flood_event_status_for(db, row, has_result=True)
    db.add(row)
    db.flush()
    product_service.sync_layers(db, row, body.artifacts_json)
    product_service.sync_area_stats(db, row)
    db.commit()
    db.refresh(row)
    return ok(product_out(row).model_dump(mode="json"), status_code=201)


@router.get("/{product_id}")
def get_product(
    product_id: uuid.UUID,
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    principal.require("product.read")
    row = _get(db, product_id, principal.org_id)
    allowed = product_service.visible_status_filter(principal)
    if allowed is not None and row.status not in allowed:
        raise APIError(404, "not_found", "Product not found")
    return ok(product_out(row).model_dump(mode="json"))


@router.patch("/{product_id}")
def update_product(
    product_id: uuid.UUID,
    body: ProductIn,
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    principal.require("product.draft")
    row = _get(db, product_id, principal.org_id)
    product_service.assert_mutable(row)
    row.title = body.title
    row.storage_uri = body.storage_uri or row.storage_uri
    row.artifacts_json = body.artifacts_json or row.artifacts_json
    row.metadata_json = product_service.to_meta_safe(body.metadata_json or row.metadata_json)
    db.commit()
    db.refresh(row)
    return ok(product_out(row).model_dump(mode="json"))


def _act(action: str, product_id, body: TransitionIn, principal, db):
    row = product_service.transition(
        db,
        _get(db, product_id, principal.org_id),
        action,
        principal,
        comment=body.comment,
        reason=body.reason,
    )
    db.commit()
    db.refresh(row)
    return ok(product_out(row).model_dump(mode="json"))


@router.post("/{product_id}/submit")
def submit_product(product_id: uuid.UUID, body: TransitionIn | None = None, principal: Principal = Depends(get_current_principal), db: Session = Depends(get_db)):
    return _act("submit", product_id, body or TransitionIn(), principal, db)


@router.post("/{product_id}/reject")
def reject_product(product_id: uuid.UUID, body: TransitionIn | None = None, principal: Principal = Depends(get_current_principal), db: Session = Depends(get_db)):
    return _act("reject", product_id, body or TransitionIn(), principal, db)


@router.post("/{product_id}/publish")
def publish_product(product_id: uuid.UUID, body: TransitionIn | None = None, principal: Principal = Depends(get_current_principal), db: Session = Depends(get_db)):
    return _act("publish", product_id, body or TransitionIn(), principal, db)


@router.post("/{product_id}/withdraw")
def withdraw_product(product_id: uuid.UUID, body: TransitionIn | None = None, principal: Principal = Depends(get_current_principal), db: Session = Depends(get_db)):
    return _act("withdraw", product_id, body or TransitionIn(), principal, db)


@router.post("/{product_id}/new-version")
def new_version(
    product_id: uuid.UUID,
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    clone = product_service.new_version(db, _get(db, product_id, principal.org_id), principal)
    db.commit()
    db.refresh(clone)
    return ok(product_out(clone).model_dump(mode="json"), status_code=201)



@router.get("/{product_id}/layers")
def list_layers(
    product_id: uuid.UUID,
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    principal.require("product.read")
    row = _get(db, product_id, principal.org_id)
    allowed = product_service.visible_status_filter(principal)
    if allowed is not None and row.status not in allowed:
        raise APIError(404, "not_found", "Product not found")
    allowed_keys = set(product_service.layer_keys_for(db, row))
    layers = (
        db.query(ProductLayer)
        .filter(ProductLayer.product_id == row.id, ProductLayer.layer_key.in_(allowed_keys | {"thematic_map", "qc_summary", "sigma0_vv_db"}))
        .all()
    )
    # If no rows yet, still return the official key list so the map client can bind switches.
    data = [ProductLayerOut.model_validate(layer).model_dump(mode="json") for layer in layers]
    meta = {
        "layer_keys": product_service.layer_keys_for(db, row),
        "has_baseline": product_service.has_baseline(db, row),
        "flood_event_status": row.flood_event_status,
        "class_map": {
            "0": "nodata",
            "1": "non_water",
            "2": "permanent_or_baseline_water",
            "3": "flood_event",
            "4": "water_lowconf",
            "5": "extracted_water",
        },
    }
    return ok(data, meta=meta)


@router.get("/{product_id}/stats")
def list_stats(
    product_id: uuid.UUID,
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    principal.require("product.read")
    row = _get(db, product_id, principal.org_id)
    allowed = product_service.visible_status_filter(principal)
    if allowed is not None and row.status not in allowed:
        raise APIError(404, "not_found", "Product not found")
    stats = db.query(ImpactStat).filter(ImpactStat.product_id == row.id).all()
    # P0/P1: never pad missing cross-stats with empty shells.
    return ok(
        [ImpactStatOut.model_validate(s).model_dump(mode="json") for s in stats],
        meta={
            "area_metrics": product_service.area_metric_rows(db, row),
            "limitation": "统计基于雷达提取范围，建成区可能低估，不含水深和人口。",
        },
    )
