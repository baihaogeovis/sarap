from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import Principal, get_current_principal
from app.core.responses import APIError, ok
from app.models import Project, Scene, SceneActivation
from app.models.base import utcnow
from app.scenes.registry import get_manifest
from app.schemas.common import SceneActivateIn, SceneActivationOut, SceneOut
from app.services import audit
from app.services.areas import baseline_warning, validate_area_config

router = APIRouter(tags=["scenes"])


@router.get("/scenes")
def list_scenes(principal: Principal = Depends(get_current_principal), db: Session = Depends(get_db)):
    principal.require("scene.read")
    rows = db.query(Scene).filter(Scene.deleted_at.is_(None)).order_by(Scene.code).all()
    return ok([SceneOut.model_validate(row).model_dump(mode="json") for row in rows])


@router.post("/projects/{project_id}/scenes")
def activate_scene(
    project_id: uuid.UUID,
    body: SceneActivateIn,
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    principal.require("scene.configure")
    project = db.get(Project, project_id)
    if project is None or project.org_id != principal.org_id:
        raise APIError(404, "not_found", "Project not found")
    scene = db.query(Scene).filter(Scene.code == body.scene_code, Scene.deleted_at.is_(None)).one_or_none()
    if scene is None:
        raise APIError(404, "not_found", f"Scene '{body.scene_code}' is not registered")
    existing = (
        db.query(SceneActivation)
        .filter(SceneActivation.project_id == project_id, SceneActivation.scene_id == scene.id)
        .one_or_none()
    )
    config = body.config_json or (get_manifest(scene.code) or {})
    if existing:
        existing.status = "enabled"
        if body.config_json:
            existing.config_json = body.config_json
        existing.activated_by = principal.id
        existing.activated_at = utcnow()
        row = existing
    else:
        row = SceneActivation(
            org_id=principal.org_id,
            project_id=project_id,
            scene_id=scene.id,
            status="enabled",
            config_json=body.config_json or config,
            activated_by=principal.id,
            activated_at=utcnow(),
        )
        db.add(row)
    if body.config_json:
        row.config_json = validate_area_config(
            db, principal.org_id, row.config_json, project_id=project_id
        )
    audit.record(
        db,
        actor_type=principal.typ,
        actor_id=principal.id,
        action="scene.activate",
        resource_type="scene_activation",
        resource_id=str(scene.id),
        org_id=principal.org_id,
        project_id=project_id,
        after={"scene_code": scene.code},
    )
    db.commit()
    db.refresh(row)
    warning = baseline_warning(db, principal.org_id, project_id=project_id)
    meta = {"warnings": [warning]} if warning else {}
    return ok(SceneActivationOut.model_validate(row).model_dump(mode="json"), meta=meta)


@router.patch("/projects/{project_id}/scenes/{scene_code}")
def update_activation(
    project_id: uuid.UUID,
    scene_code: str,
    body: SceneActivateIn,
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    principal.require("scene.configure")
    scene = db.query(Scene).filter(Scene.code == scene_code).one_or_none()
    if scene is None:
        raise APIError(404, "not_found", "Scene not found")
    row = (
        db.query(SceneActivation)
        .filter(
            SceneActivation.project_id == project_id,
            SceneActivation.scene_id == scene.id,
            SceneActivation.org_id == principal.org_id,
        )
        .one_or_none()
    )
    if row is None:
        raise APIError(404, "not_found", "Scene is not activated on this project")
    if body.config_json:
        row.config_json = validate_area_config(
            db, principal.org_id, body.config_json, project_id=project_id
        )
    db.commit()
    db.refresh(row)
    warning = baseline_warning(db, principal.org_id, project_id=project_id)
    meta = {"warnings": [warning]} if warning else {}
    return ok(SceneActivationOut.model_validate(row).model_dump(mode="json"), meta=meta)


@router.get("/projects/{project_id}/scenes")
def list_activations(
    project_id: uuid.UUID,
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    principal.require("scene.read")
    rows = (
        db.query(SceneActivation)
        .filter(SceneActivation.project_id == project_id, SceneActivation.org_id == principal.org_id)
        .all()
    )
    return ok([SceneActivationOut.model_validate(row).model_dump(mode="json") for row in rows])
