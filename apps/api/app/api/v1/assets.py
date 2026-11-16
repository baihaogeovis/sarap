from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import Principal, get_current_principal
from app.core.responses import APIError, ok
from app.models import DataAsset, DataAssetVersion
from app.models.base import utcnow
from app.schemas.common import (
    DataAssetIn,
    DataAssetOut,
    DataAssetVersionIn,
    DataAssetVersionOut,
    ReviewIn,
)
from app.services import audit
from app.services.baselines import version_is_referenced

router = APIRouter(tags=["data-assets"])

VERSION_TRANSITIONS = {
    ("draft", "submit"): "pending_review",
    ("pending_review", "publish"): "published",
    ("pending_review", "reject"): "rejected",
    ("rejected", "submit"): "pending_review",
    ("published", "deprecate"): "deprecated",
    ("draft", "publish"): "published",  # admin may publish a reviewed-ready draft
}


def _asset(db: Session, asset_id: uuid.UUID, org_id: uuid.UUID) -> DataAsset:
    row = db.get(DataAsset, asset_id)
    if row is None or row.org_id != org_id or row.deleted_at is not None:
        raise APIError(404, "not_found", "Data asset not found")
    return row


def _version(db: Session, version_id: uuid.UUID, org_id: uuid.UUID) -> DataAssetVersion:
    row = db.get(DataAssetVersion, version_id)
    if row is None or row.org_id != org_id or row.deleted_at is not None:
        raise APIError(404, "not_found", "Data asset version not found")
    return row


@router.get("/data-assets")
def list_assets(
    project_id: uuid.UUID | None = Query(default=None),
    area_id: uuid.UUID | None = Query(default=None),
    asset_type: str | None = Query(default=None),
    review_status: str | None = Query(default=None),
    valid_at: datetime | None = Query(default=None),
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    principal.require("baseline.read", "dataset.read")
    q = db.query(DataAsset).filter(DataAsset.org_id == principal.org_id, DataAsset.deleted_at.is_(None))
    if project_id:
        q = q.filter((DataAsset.project_id == project_id) | (DataAsset.project_id.is_(None)))
    if area_id:
        q = q.filter((DataAsset.area_id == area_id) | (DataAsset.area_id.is_(None)))
    if asset_type:
        q = q.filter(DataAsset.asset_type == asset_type)
    rows = q.order_by(DataAsset.asset_code).all()
    payload = []
    for row in rows:
        item = DataAssetOut.model_validate(row).model_dump(mode="json")
        versions = (
            db.query(DataAssetVersion)
            .filter(DataAssetVersion.asset_id == row.id, DataAssetVersion.deleted_at.is_(None))
            .order_by(DataAssetVersion.created_at.desc())
            .all()
        )
        if review_status:
            versions = [v for v in versions if v.review_status == review_status]
        if valid_at:
            versions = [
                v
                for v in versions
                if v.valid_from <= valid_at and (v.valid_to is None or v.valid_to > valid_at)
            ]
        item["versions"] = [DataAssetVersionOut.model_validate(v).model_dump(mode="json") for v in versions]
        payload.append(item)
    return ok(payload, meta={"total": len(payload)})


@router.post("/data-assets")
def create_asset(
    body: DataAssetIn,
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    principal.require("baseline.write")
    row = DataAsset(
        org_id=principal.org_id,
        project_id=body.project_id,
        area_id=body.area_id,
        asset_code=body.asset_code,
        name=body.name,
        asset_type=body.asset_type,
        description=body.description,
        owner=body.owner,
        default_crs=body.default_crs,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return ok(DataAssetOut.model_validate(row).model_dump(mode="json"), status_code=201)


@router.get("/data-assets/{asset_id}")
def get_asset(
    asset_id: uuid.UUID,
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    principal.require("baseline.read", "dataset.read")
    row = _asset(db, asset_id, principal.org_id)
    return ok(DataAssetOut.model_validate(row).model_dump(mode="json"))


@router.patch("/data-assets/{asset_id}")
def update_asset(
    asset_id: uuid.UUID,
    body: DataAssetIn,
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    principal.require("baseline.write")
    row = _asset(db, asset_id, principal.org_id)
    row.name = body.name
    row.description = body.description
    row.owner = body.owner
    row.default_crs = body.default_crs
    row.project_id = body.project_id
    row.area_id = body.area_id
    db.commit()
    db.refresh(row)
    return ok(DataAssetOut.model_validate(row).model_dump(mode="json"))


@router.post("/data-assets/{asset_id}/versions")
def create_version(
    asset_id: uuid.UUID,
    body: DataAssetVersionIn,
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    principal.require("baseline.write")
    asset = _asset(db, asset_id, principal.org_id)
    exists = (
        db.query(DataAssetVersion)
        .filter(DataAssetVersion.asset_id == asset.id, DataAssetVersion.version_no == body.version_no)
        .first()
    )
    if exists:
        raise APIError(409, "conflict", "version_no already exists for this asset")
    row = DataAssetVersion(
        org_id=principal.org_id,
        asset_id=asset.id,
        version_no=body.version_no,
        valid_from=body.valid_from,
        valid_to=body.valid_to,
        applicable_area_geojson=body.applicable_area_geojson,
        applicable_area_name=body.applicable_area_name,
        review_status="draft",
        source=body.source,
        algorithm_profile_id=body.algorithm_profile_id,
        spatial_res_m=body.spatial_res_m,
        crs=body.crs,
        gsd_note=body.gsd_note,
        checksum=body.checksum,
        byte_size=body.byte_size,
        storage_uri=body.storage_uri,
        preview_uri=body.preview_uri,
        schema_json=body.schema_json,
        lineage_json=body.lineage_json,
        created_by=principal.id if principal.typ == "user" else None,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return ok(DataAssetVersionOut.model_validate(row).model_dump(mode="json"), status_code=201)


@router.get("/data-assets/{asset_id}/versions")
def list_versions(
    asset_id: uuid.UUID,
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    principal.require("baseline.read", "dataset.read")
    _asset(db, asset_id, principal.org_id)
    rows = (
        db.query(DataAssetVersion)
        .filter(DataAssetVersion.asset_id == asset_id, DataAssetVersion.deleted_at.is_(None))
        .order_by(DataAssetVersion.created_at.desc())
        .all()
    )
    return ok([DataAssetVersionOut.model_validate(r).model_dump(mode="json") for r in rows])


def _transition(db, row: DataAssetVersion, action: str, principal: Principal, comment: str) -> DataAssetVersion:
    if action == "publish":
        principal.require("baseline.publish", "baseline.review")
    elif action == "submit":
        principal.require("baseline.write", "baseline.review")
    else:
        principal.require("baseline.review", "baseline.publish")
    key = (row.review_status, action)
    if key not in VERSION_TRANSITIONS:
        raise APIError(
            409,
            "invalid_transition",
            f"Cannot {action} a baseline version in review_status {row.review_status}",
        )
    before = {"review_status": row.review_status}
    row.review_status = VERSION_TRANSITIONS[key]
    if action in {"publish", "reject", "deprecate"}:
        row.reviewer_id = principal.id if principal.typ == "user" else row.reviewer_id
        row.reviewed_at = utcnow()
        row.review_comment = comment
    audit.record(
        db,
        actor_type=principal.typ,
        actor_id=principal.id,
        action=f"baseline.{action}",
        resource_type="data_asset_version",
        resource_id=str(row.id),
        org_id=principal.org_id,
        before=before,
        after={"review_status": row.review_status},
    )
    db.add(row)
    return row


@router.post("/data-asset-versions/{version_id}/submit")
def submit_version(
    version_id: uuid.UUID,
    body: ReviewIn | None = None,
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    row = _transition(db, _version(db, version_id, principal.org_id), "submit", principal, (body.comment if body else ""))
    db.commit()
    db.refresh(row)
    return ok(DataAssetVersionOut.model_validate(row).model_dump(mode="json"))


@router.post("/data-asset-versions/{version_id}/publish")
def publish_version(
    version_id: uuid.UUID,
    body: ReviewIn | None = None,
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    row = _transition(db, _version(db, version_id, principal.org_id), "publish", principal, (body.comment if body else ""))
    db.commit()
    db.refresh(row)
    return ok(DataAssetVersionOut.model_validate(row).model_dump(mode="json"))


@router.post("/data-asset-versions/{version_id}/reject")
def reject_version(
    version_id: uuid.UUID,
    body: ReviewIn | None = None,
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    row = _transition(db, _version(db, version_id, principal.org_id), "reject", principal, (body.comment if body else "") or (body.reason if body else ""))
    db.commit()
    db.refresh(row)
    return ok(DataAssetVersionOut.model_validate(row).model_dump(mode="json"))


@router.post("/data-asset-versions/{version_id}/deprecate")
def deprecate_version(
    version_id: uuid.UUID,
    body: ReviewIn | None = None,
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    row = _transition(db, _version(db, version_id, principal.org_id), "deprecate", principal, (body.comment if body else ""))
    db.commit()
    db.refresh(row)
    return ok(DataAssetVersionOut.model_validate(row).model_dump(mode="json"))



@router.delete("/data-asset-versions/{version_id}")
def delete_version(
    version_id: uuid.UUID,
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    """Referenced versions cannot be soft-deleted; deprecate them instead."""
    principal.require("baseline.write", "baseline.review")
    row = _version(db, version_id, principal.org_id)
    if version_is_referenced(db, row.id):
        raise APIError(
            409,
            "BASELINE_IN_USE",
            "该本底版本已被任务或产品引用，只允许废弃（deprecate），禁止软删除",
        )
    from app.models.base import utcnow

    row.deleted_at = utcnow()
    db.commit()
    return ok({"deleted": True})
