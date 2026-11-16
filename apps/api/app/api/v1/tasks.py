from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.v1.serializers import task_out
from app.core.db import get_db
from app.core.deps import Principal, get_current_principal
from app.core.responses import APIError, ok
from app.models import Dataset, Project, Task
from app.schemas.common import TaskIn
from app.services import task as task_service
from app.services.baselines import (
    compute_idempotency_key,
    dataset_imagery_fields,
    resolve_baseline_version,
)

router = APIRouter(prefix="/tasks", tags=["tasks"])


def _get_task(db: Session, task_id: uuid.UUID, org_id: uuid.UUID) -> Task:
    row = db.get(Task, task_id)
    if row is None or row.org_id != org_id or row.deleted_at is not None:
        raise APIError(404, "not_found", "Task not found")
    return row


@router.get("")
def list_tasks(
    project_id: uuid.UUID | None = Query(default=None),
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    principal.require("task.read")
    q = db.query(Task).filter(Task.org_id == principal.org_id, Task.deleted_at.is_(None))
    if project_id:
        q = q.filter(Task.project_id == project_id)
    rows = q.order_by(Task.created_at.desc()).all()
    return ok([task_out(r).model_dump(mode="json") for r in rows], meta={"total": len(rows)})


@router.post("")
def create_task(
    body: TaskIn,
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    principal.require("task.create")
    project = db.get(Project, body.project_id)
    if project is None or project.org_id != principal.org_id:
        raise APIError(404, "not_found", "Project not found")
    scene, activation = task_service.require_scene_enabled(db, body.project_id, body.scene_code)
    area = task_service.get_area(db, body.area_id, principal.org_id) if body.area_id else None
    dataset = db.get(Dataset, body.imagery_dataset_id) if body.imagery_dataset_id else None
    if body.imagery_dataset_id and (dataset is None or dataset.org_id != principal.org_id):
        raise APIError(404, "not_found", "Imagery dataset not found")
    acq_start, acq_end, s1_id = dataset_imagery_fields(dataset)
    acq_start = body.acquisition_start or acq_start
    acq_end = body.acquisition_end or acq_end
    s1_id = body.s1_product_id or s1_id
    config = (area.config_json if area is not None else None) or activation.config_json
    # Resolve official baseline (published data_asset_version only). Legacy baseline_asset_id is ignored.
    resolved = resolve_baseline_version(
        db,
        org_id=principal.org_id,
        area=area,
        project_id=body.project_id,
        acquired_at=acq_start or body.data_ready_at,
        config=config,
        explicit_version_id=body.baseline_version_id,
    )
    baseline_version_id = resolved.id if resolved else None
    idem_key = body.idempotency_key
    if not idem_key and s1_id:
        # Auto-key only when a Sentinel-1 PRODUCT-ID is known; otherwise leave
        # null so exploratory tasks without imagery do not collide.
        idem_key = compute_idempotency_key(
            scene_id=scene.id,
            area_id=body.area_id,
            s1_product_id=s1_id,
            baseline_version_id=baseline_version_id,
            algo_profile_id=body.algo_profile_id,
            params=body.params_json,
        )
    if not body.force_rerun:
        existing = task_service.find_by_idempotency(db, principal.org_id, idem_key)
        if existing is not None:
            return ok(task_out(existing).model_dump(mode="json"), meta={"idempotent": True})
    if body.force_rerun:
        idem_key = f"{idem_key}::rerun::{uuid.uuid4().hex[:8]}"
    code = f"T-{uuid.uuid4().hex[:10]}"
    params = dict(body.params_json or {})
    if body.imagery_dataset_id:
        params.setdefault("imagery_dataset_id", str(body.imagery_dataset_id))
    if s1_id:
        params.setdefault("s1_product_id", s1_id)
    # Area config (not a hardcoded basin) is preferred; fall back to scene activation config.
    if area is not None:
        params.setdefault("area_config", area.config_json)
        params.setdefault("analysis_crs", area.analysis_crs)
        params.setdefault("grid", {"res_m": area.grid_res_m, "origin_x": area.grid_origin_x, "origin_y": area.grid_origin_y})
    params.setdefault("pilot_config", activation.config_json)
    row = Task(
        org_id=principal.org_id,
        project_id=body.project_id,
        area_id=body.area_id,
        scene_id=scene.id,
        scene_code=scene.code,
        code=code,
        title=body.title,
        task_type=body.task_type,
        status="queued",
        priority="emergency" if body.emergency else "normal",
        emergency=body.emergency,
        params_json=params,
        assignee_id=principal.id,
        idempotency_key=idem_key,
        algo_profile_id=body.algo_profile_id,
        baseline_version_id=baseline_version_id,
        data_ready_at=body.data_ready_at,
        acquisition_start=acq_start,
        acquisition_end=acq_end,
        s1_product_id=s1_id or "",
    )
    db.add(row)
    db.flush()
    try:
        task_service.dispatch(db, row, principal)
    except APIError as exc:
        db.commit()
        raise exc
    db.commit()
    db.refresh(row)
    return ok(task_out(row).model_dump(mode="json"), status_code=201)


@router.get("/{task_id}")
def get_task(
    task_id: uuid.UUID,
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    principal.require("task.read")
    return ok(task_out(_get_task(db, task_id, principal.org_id)).model_dump(mode="json"))


@router.post("/{task_id}/cancel")
def cancel_task(
    task_id: uuid.UUID,
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    row = task_service.cancel(db, _get_task(db, task_id, principal.org_id), principal)
    db.commit()
    db.refresh(row)
    return ok(task_out(row).model_dump(mode="json"))


@router.post("/{task_id}/retry")
def retry_task(
    task_id: uuid.UUID,
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    row = _get_task(db, task_id, principal.org_id)
    try:
        row = task_service.retry(db, row, principal)
    except APIError as exc:
        db.commit()
        raise exc
    db.commit()
    db.refresh(row)
    return ok(task_out(row).model_dump(mode="json"))



@router.post("/{task_id}/rerun")
def rerun_task(
    task_id: uuid.UUID,
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    """force_rerun: create a new task from the previous one (new idempotency suffix)."""
    principal.require("task.retry", "task.create")
    src = _get_task(db, task_id, principal.org_id)
    body = TaskIn(
        project_id=src.project_id,
        scene_code=src.scene_code,
        task_type=src.task_type,
        title=src.title,
        params_json=src.params_json,
        emergency=src.emergency,
        area_id=src.area_id,
        algo_profile_id=src.algo_profile_id,
        baseline_version_id=src.baseline_version_id,
        data_ready_at=src.data_ready_at,
        idempotency_key=src.idempotency_key,
        acquisition_start=src.acquisition_start,
        acquisition_end=src.acquisition_end,
        s1_product_id=src.s1_product_id,
        force_rerun=True,
    )
    return create_task(body, principal, db)
