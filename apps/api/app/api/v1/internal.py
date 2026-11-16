from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.v1.serializers import product_out
from app.core.db import get_db
from app.core.deps import verify_internal_or_service
from app.core.responses import APIError, ok
from app.models import Area, Dataset, Product, Task
from app.models.base import utcnow
from app.schemas.common import InternalProductIn
from app.services import audit
from app.services import product as product_service
from app.services.baselines import fill_imagery_fields, require_applicable_version
from app.services.product import to_meta_safe

router = APIRouter(prefix="/internal", tags=["internal"], dependencies=[Depends(verify_internal_or_service)])


@router.post("/products")
def ingest_product(body: InternalProductIn, db: Session = Depends(get_db)):
    task = db.get(Task, body.task_id)
    if task is None:
        raise APIError(404, "not_found", "Task not found")
    from app.services.product import HARD_ERROR_CODES, reject_depth_fields

    reject_depth_fields(body.metadata_json)
    if body.error_code in HARD_ERROR_CODES:
        task.status = "failed"
        task.error_code = body.error_code
        task.finished_at = utcnow()
        db.commit()
        raise APIError(409, "hard_error", f"Hard processing error: {body.error_code}")
    area = db.get(Area, task.area_id) if task.area_id else None
    acquired_at = body.acquisition_start or task.acquisition_start or task.data_ready_at
    published = (
        require_applicable_version(
            db,
            body.baseline_version_id,
            org_id=task.org_id,
            area=area,
            acquired_at=acquired_at,
        )
        if body.baseline_version_id
        else None
    )
    has_base = published is not None
    row = Product(
        org_id=task.org_id,
        project_id=task.project_id,
        area_id=task.area_id,
        scene_id=task.scene_id,
        scene_code=task.scene_code,
        task_id=task.id,
        imagery_dataset_id=body.imagery_dataset_id,
        baseline_asset_id=body.baseline_asset_id,
        data_asset_id=(published.asset_id if published else body.data_asset_id),
        baseline_version=(published.version_no if published else ""),
        baseline_version_id=(published.id if published else None),
        engine_name=body.engine_name,
        engine_params_json=body.engine_params_json,
        code=body.code or f"P-{uuid.uuid4().hex[:10]}",
        title=body.title,
        product_type=body.product_type,
        version=1,
        status="draft",
        storage_uri=body.storage_uri,
        artifacts_json=body.artifacts_json,
        metadata_json=to_meta_safe(body.metadata_json),
        flood_event_status="none",
        extracted_water_ha=None if has_base else product_service.round_ha(body.extracted_water_ha),
        water_current_ha=product_service.round_ha(body.water_current_ha) if has_base else None,
        flood_event_ha=product_service.round_ha(body.flood_event_ha) if has_base else None,
        lowconf_ha=product_service.round_ha(body.lowconf_ha),
        data_ready_at=task.data_ready_at,
        submitted_at=task.submitted_at,
        processed_at=body.processed_at or utcnow(),
        suggested_target_minutes=int((task.params_json or {}).get("suggested_target_minutes") or 240),
        acquisition_start=body.acquisition_start or task.acquisition_start,
        acquisition_end=body.acquisition_end or task.acquisition_end,
        s1_product_id=body.s1_product_id or task.s1_product_id or "",
    )
    if body.imagery_dataset_id:
        fill_imagery_fields(row, dataset=db.get(Dataset, body.imagery_dataset_id))
    elif task.imagery_dataset_id if hasattr(task, "imagery_dataset_id") else None:
        pass
    row.flood_event_status = product_service.flood_event_status_for(db, row, has_result=True)
    db.add(row)
    db.flush()
    product_service.sync_layers(db, row, body.artifacts_json)
    product_service.sync_area_stats(db, row)
    # QC warnings never block P0 ingest/publishability.
    task.status = "succeeded"
    task.progress = 100
    task.finished_at = utcnow()
    if task.processed_at is None:
        task.processed_at = row.processed_at
    audit.record(
        db,
        actor_type="service",
        actor_id=None,
        action="product.ingest",
        resource_type="product",
        resource_id="pending",
        org_id=task.org_id,
        project_id=task.project_id,
        after={"task_id": str(task.id), "product_type": body.product_type},
    )
    db.commit()
    db.refresh(row)
    return ok(product_out(row).model_dump(mode="json"), status_code=201)


@router.post("/tasks/{task_id}/progress")
def update_progress(task_id: uuid.UUID, payload: dict, db: Session = Depends(get_db)):
    from app.services import task as task_service

    task = db.get(Task, task_id)
    if task is None:
        raise APIError(404, "not_found", "Task not found")
    task_service.apply_event(db, task, payload)
    db.commit()
    db.refresh(task)
    return ok({"id": str(task.id), "status": task.status, "progress": task.progress, "step": task.step})



@router.post("/tasks/{task_id}/events")
def task_events(task_id: uuid.UUID, payload: dict, db: Session = Depends(get_db)):
    from app.services import task as task_service

    task = db.get(Task, task_id)
    if task is None:
        raise APIError(404, "not_found", "Task not found")
    task_service.apply_event(db, task, payload)
    db.commit()
    db.refresh(task)
    return ok(
        {
            "id": str(task.id),
            "status": task.status,
            "progress": task.progress,
            "step": task.step,
            "error_code": task.error_code,
            "data_ready_at": task.data_ready_at.isoformat() if task.data_ready_at else None,
            "submitted_at": task.submitted_at.isoformat() if task.submitted_at else None,
            "processed_at": task.processed_at.isoformat() if task.processed_at else None,
        }
    )
