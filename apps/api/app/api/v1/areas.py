from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import Principal, get_current_principal
from app.core.responses import APIError, ok
from app.models import Area, Project
from app.schemas.common import AreaIn, AreaOut
from app.services import audit
from app.services.areas import baseline_warning, validate_area_config
from app.services.baselines import centroid_lon, suggest_analysis_crs

router = APIRouter(tags=["areas"])



def _analysis_crs(body, existing: str | None = None) -> tuple[str, dict | None]:
    lon = centroid_lon(body.aoi_geojson, body.bbox_json)
    suggested = suggest_analysis_crs(lon) if lon is not None else None
    if body.analysis_crs:
        warning = None
        if suggested and body.analysis_crs != suggested:
            warning = {
                "code": "analysis_crs_mismatch",
                "message": (
                    f"已采用调用方指定的 {body.analysis_crs}；按区域中央经线建议 {suggested}。"
                    "EPSG:4548（中央经线 117E）只是 116°E 附近示例区的默认，不是全国默认。"
                ),
            }
        return body.analysis_crs, warning
    if suggested:
        return suggested, None
    if existing:
        return existing, None
    return "EPSG:4548", {
        "code": "analysis_crs_example_default",
        "message": "无法从 AOI 推算中央经线，暂用示例 EPSG:4548（CM 117E）。新区域请提供 AOI 或显式指定 analysis_crs。",
    }


def _get_area(db: Session, area_id: uuid.UUID, org_id: uuid.UUID) -> Area:
    row = db.get(Area, area_id)
    if row is None or row.org_id != org_id or row.deleted_at is not None:
        raise APIError(404, "not_found", "Area not found")
    return row


@router.get("/projects/{project_id}/areas")
def list_areas(
    project_id: uuid.UUID,
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    principal.require("area.read")
    rows = (
        db.query(Area)
        .filter(Area.org_id == principal.org_id, Area.project_id == project_id, Area.deleted_at.is_(None))
        .order_by(Area.created_at)
        .all()
    )
    return ok([AreaOut.model_validate(r).model_dump(mode="json") for r in rows])


@router.post("/projects/{project_id}/areas")
def create_area(
    project_id: uuid.UUID,
    body: AreaIn,
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    principal.require("area.manage")
    project = db.get(Project, project_id)
    if project is None or project.org_id != principal.org_id or project.deleted_at is not None:
        raise APIError(404, "not_found", "Project not found")
    exists = (
        db.query(Area)
        .filter(Area.org_id == principal.org_id, Area.code == body.code, Area.deleted_at.is_(None))
        .first()
    )
    if exists:
        raise APIError(409, "conflict", "An area with this code already exists in the organization")
    config = validate_area_config(db, principal.org_id, body.config_json, project_id=project_id)
    analysis_crs, crs_warning = _analysis_crs(body)
    row = Area(
        org_id=principal.org_id,
        project_id=project_id,
        code=body.code,
        name=body.name,
        is_pilot=body.is_pilot,
        timezone=body.timezone,
        aoi_geojson=body.aoi_geojson,
        bbox_json=body.bbox_json,
        analysis_crs=analysis_crs,
        exchange_crs=body.exchange_crs,
        grid_res_m=body.grid_res_m,
        grid_origin_x=body.grid_origin_x,
        grid_origin_y=body.grid_origin_y,
        config_json=config,
    )
    db.add(row)
    db.flush()
    audit.record(
        db,
        actor_type=principal.typ,
        actor_id=principal.id,
        action="area.create",
        resource_type="area",
        resource_id=str(row.id),
        org_id=principal.org_id,
        project_id=project_id,
        after={"code": row.code, "is_pilot": row.is_pilot},
    )
    db.commit()
    db.refresh(row)
    warnings = []
    if crs_warning:
        warnings.append(crs_warning)
    warning = baseline_warning(db, principal.org_id, project_id=project_id, area_id=row.id)
    if warning:
        warnings.append(warning)
    meta = {"warnings": warnings} if warnings else {}
    return ok(AreaOut.model_validate(row).model_dump(mode="json"), meta=meta, status_code=201)


@router.get("/areas/{area_id}")
def get_area(
    area_id: uuid.UUID,
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    principal.require("area.read")
    return ok(AreaOut.model_validate(_get_area(db, area_id, principal.org_id)).model_dump(mode="json"))


@router.patch("/areas/{area_id}")
def update_area(
    area_id: uuid.UUID,
    body: AreaIn,
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    principal.require("area.manage")
    row = _get_area(db, area_id, principal.org_id)
    row.name = body.name
    row.is_pilot = body.is_pilot
    row.timezone = body.timezone
    row.aoi_geojson = body.aoi_geojson
    row.bbox_json = body.bbox_json
    analysis_crs, crs_warning = _analysis_crs(body, existing=row.analysis_crs)
    row.analysis_crs = analysis_crs
    row.exchange_crs = body.exchange_crs
    row.grid_res_m = body.grid_res_m
    row.grid_origin_x = body.grid_origin_x
    row.grid_origin_y = body.grid_origin_y
    row.config_json = validate_area_config(
        db, principal.org_id, body.config_json, project_id=row.project_id, area_id=row.id
    )
    db.commit()
    db.refresh(row)
    warnings = []
    if crs_warning:
        warnings.append(crs_warning)
    warning = baseline_warning(db, principal.org_id, project_id=row.project_id, area_id=row.id)
    if warning:
        warnings.append(warning)
    meta = {"warnings": warnings} if warnings else {}
    return ok(AreaOut.model_validate(row).model_dump(mode="json"), meta=meta)
