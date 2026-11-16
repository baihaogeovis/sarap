from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import Principal, get_current_principal
from app.core.responses import APIError, ok
from app.models import BaselineAsset, Dataset
from app.models.base import utcnow
from app.schemas.common import BaselineIn, BaselineOut, BaselineReviewIn, DatasetIn, DatasetOut
from app.services import audit

router = APIRouter(tags=["catalog"])

ALLOWED_REVIEW = {"draft", "pending_review", "published", "rejected", "deprecated"}


@router.get("/datasets")
def list_datasets(
    project_id: uuid.UUID | None = Query(default=None),
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    principal.require("dataset.read")
    q = db.query(Dataset).filter(Dataset.org_id == principal.org_id, Dataset.deleted_at.is_(None))
    if project_id:
        q = q.filter((Dataset.project_id == project_id) | (Dataset.project_id.is_(None)))
    rows = q.order_by(Dataset.created_at.desc()).all()
    return ok([DatasetOut.model_validate(r).model_dump(mode="json") for r in rows])


@router.post("/datasets")
def create_dataset(
    body: DatasetIn,
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    principal.require("dataset.write")
    row = Dataset(
        org_id=principal.org_id,
        project_id=body.project_id,
        code=body.code,
        name=body.name,
        dataset_type=body.dataset_type,
        source=body.source,
        format=body.format,
        crs=body.crs,
        bbox_json=body.bbox_json,
        time_start=body.time_start,
        time_end=body.time_end,
        s1_product_id=body.s1_product_id or "",
        storage_uri=body.storage_uri,
        metadata_json=body.metadata_json,
        tags=body.tags,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return ok(DatasetOut.model_validate(row).model_dump(mode="json"), status_code=201)


@router.get("/datasets/{dataset_id}")
def get_dataset(
    dataset_id: uuid.UUID,
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    principal.require("dataset.read")
    row = db.get(Dataset, dataset_id)
    if row is None or row.org_id != principal.org_id or row.deleted_at is not None:
        raise APIError(404, "not_found", "Dataset not found")
    return ok(DatasetOut.model_validate(row).model_dump(mode="json"))


@router.get("/baselines")
def list_baselines(
    project_id: uuid.UUID | None = Query(default=None),
    category: str | None = Query(default=None),
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    principal.require("dataset.read")
    q = db.query(BaselineAsset).filter(BaselineAsset.org_id == principal.org_id, BaselineAsset.deleted_at.is_(None))
    if project_id:
        q = q.filter((BaselineAsset.project_id == project_id) | (BaselineAsset.project_id.is_(None)))
    if category:
        q = q.filter(BaselineAsset.category == category)
    rows = q.order_by(BaselineAsset.code, BaselineAsset.version).all()
    return ok([BaselineOut.model_validate(r).model_dump(mode="json") for r in rows])


@router.post("/baselines")
def create_baseline(
    body: BaselineIn,
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    principal.require("baseline.write")
    dataset = db.get(Dataset, body.dataset_id)
    if dataset is None or dataset.org_id != principal.org_id:
        raise APIError(404, "not_found", "Dataset not found")
    row = BaselineAsset(
        org_id=principal.org_id,
        project_id=body.project_id,
        dataset_id=body.dataset_id,
        code=body.code,
        name=body.name,
        category=body.category,
        version=body.version,
        valid_from=body.valid_from,
        valid_to=body.valid_to,
        applicable_area_json=body.applicable_area_json,
        applicable_area_name=body.applicable_area_name,
        review_status="draft",
        metadata_json=body.metadata_json,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return ok(BaselineOut.model_validate(row).model_dump(mode="json"), status_code=201)


@router.post("/baselines/{baseline_id}/review")
def review_baseline(
    baseline_id: uuid.UUID,
    body: BaselineReviewIn,
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    principal.require("baseline.review")
    if body.review_status not in ALLOWED_REVIEW:
        raise APIError(422, "validation_error", f"Invalid review_status {body.review_status}")
    row = db.get(BaselineAsset, baseline_id)
    if row is None or row.org_id != principal.org_id:
        raise APIError(404, "not_found", "Baseline not found")
    before = {"review_status": row.review_status}
    row.review_status = body.review_status
    row.reviewer_id = principal.id
    row.reviewed_at = utcnow()
    row.review_comment = body.comment
    audit.record(
        db,
        actor_type=principal.typ,
        actor_id=principal.id,
        action="baseline.review",
        resource_type="baseline",
        resource_id=str(row.id),
        org_id=principal.org_id,
        project_id=row.project_id,
        before=before,
        after={"review_status": row.review_status},
    )
    db.commit()
    db.refresh(row)
    return ok(BaselineOut.model_validate(row).model_dump(mode="json"))
