from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.v1.serializers import briefing_out
from app.core.db import get_db
from app.core.deps import Principal, get_current_principal
from app.core.responses import APIError, ok
from app.models import Briefing, Project, Scene
from app.models.base import utcnow
from app.schemas.common import BriefingIn
from app.services import audit

router = APIRouter(prefix="/briefings", tags=["briefings"])


def _get(db: Session, briefing_id: uuid.UUID, org_id: uuid.UUID) -> Briefing:
    row = db.get(Briefing, briefing_id)
    if row is None or row.org_id != org_id or row.deleted_at is not None:
        raise APIError(404, "not_found", "Briefing not found")
    return row


@router.get("")
def list_briefings(
    project_id: uuid.UUID | None = Query(default=None),
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    principal.require("briefing.read")
    q = db.query(Briefing).filter(Briefing.org_id == principal.org_id, Briefing.deleted_at.is_(None))
    if project_id:
        q = q.filter(Briefing.project_id == project_id)
    if "admin" not in principal.roles and "duty_officer" not in principal.roles:
        q = q.filter(Briefing.status == "published")
    rows = q.order_by(Briefing.created_at.desc()).all()
    return ok([briefing_out(r).model_dump(mode="json") for r in rows])


@router.post("")
def create_briefing(
    body: BriefingIn,
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    principal.require("briefing.write")
    project = db.get(Project, body.project_id)
    if project is None or project.org_id != principal.org_id:
        raise APIError(404, "not_found", "Project not found")
    scene = db.query(Scene).filter(Scene.code == body.scene_code).one_or_none() if body.scene_code else None
    row = Briefing(
        org_id=principal.org_id,
        project_id=body.project_id,
        scene_id=scene.id if scene else None,
        scene_code=body.scene_code,
        code=f"B-{uuid.uuid4().hex[:10]}",
        title=body.title,
        status="draft",
        content_json=body.content_json,
        product_ids=[str(i) for i in body.product_ids],
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return ok(briefing_out(row).model_dump(mode="json"), status_code=201)


@router.get("/{briefing_id}")
def get_briefing(
    briefing_id: uuid.UUID,
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    principal.require("briefing.read")
    row = _get(db, briefing_id, principal.org_id)
    if "admin" not in principal.roles and "duty_officer" not in principal.roles and row.status != "published":
        raise APIError(404, "not_found", "Briefing not found")
    return ok(briefing_out(row).model_dump(mode="json"))


@router.patch("/{briefing_id}")
def update_briefing(
    briefing_id: uuid.UUID,
    body: BriefingIn,
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    principal.require("briefing.write")
    row = _get(db, briefing_id, principal.org_id)
    if row.status != "draft":
        raise APIError(409, "invalid_transition", "Only draft briefings can be edited")
    row.title = body.title
    row.content_json = body.content_json
    row.product_ids = [str(i) for i in body.product_ids]
    db.commit()
    db.refresh(row)
    return ok(briefing_out(row).model_dump(mode="json"))


@router.post("/{briefing_id}/publish")
def publish_briefing(
    briefing_id: uuid.UUID,
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    principal.require("briefing.publish")
    row = _get(db, briefing_id, principal.org_id)
    if row.status != "draft":
        raise APIError(409, "invalid_transition", "Only draft briefings can be published")
    row.status = "published"
    row.published_at = utcnow()
    audit.record(
        db,
        actor_type=principal.typ,
        actor_id=principal.id,
        action="briefing.publish",
        resource_type="briefing",
        resource_id=str(row.id),
        org_id=principal.org_id,
        project_id=row.project_id,
    )
    db.commit()
    db.refresh(row)
    return ok(briefing_out(row).model_dump(mode="json"))



@router.post("/{briefing_id}/archive")
def archive_briefing(
    briefing_id: uuid.UUID,
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    principal.require("briefing.publish", "briefing.write")
    row = _get(db, briefing_id, principal.org_id)
    if row.status not in {"draft", "published"}:
        raise APIError(409, "invalid_transition", "Only draft or published briefings can be archived")
    row.status = "archived"
    audit.record(
        db,
        actor_type=principal.typ,
        actor_id=principal.id,
        action="briefing.archive",
        resource_type="briefing",
        resource_id=str(row.id),
        org_id=principal.org_id,
        project_id=row.project_id,
    )
    db.commit()
    db.refresh(row)
    return ok(briefing_out(row).model_dump(mode="json"))
