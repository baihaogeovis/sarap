from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.v1.serializers import briefing_out
from app.core.db import get_db
from app.core.deps import Principal, get_current_principal
from app.core.responses import APIError, ok
from app.models import Area, Briefing, Product, Project, Scene
from app.models.base import utcnow
from app.schemas.common import BriefingIn
from app.services import audit
from app.services.briefing_view import briefing_document, preview_briefing

router = APIRouter(prefix="/briefings", tags=["briefings"])


def _require_published_products(db: Session, org_id: uuid.UUID, product_ids: list) -> None:
    for raw in product_ids or []:
        try:
            product_id = raw if isinstance(raw, uuid.UUID) else uuid.UUID(str(raw))
        except (TypeError, ValueError) as exc:
            raise APIError(422, "validation_error", "简报引用了无法识别的产品") from exc
        product = db.get(Product, product_id)
        if product is None or product.org_id != org_id or product.deleted_at is not None:
            raise APIError(422, "validation_error", "简报引用了不存在的产品")
        if product.status != "published":
            raise APIError(409, "unpublished_product", "简报发布只能引用已发布产品")


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


@router.get("/preview")
def preview(
    project_id: uuid.UUID = Query(),
    area_id: uuid.UUID = Query(),
    scene_code: str | None = Query(default=None),
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    """Default briefing for one area. Published products only."""
    principal.require("briefing.read")
    project = db.get(Project, project_id)
    if project is None or project.org_id != principal.org_id or project.deleted_at is not None:
        raise APIError(404, "not_found", "Project not found")
    area = db.get(Area, area_id)
    if area is None or area.org_id != principal.org_id or area.project_id != project.id or area.deleted_at is not None:
        raise APIError(404, "not_found", "Area not found")
    return ok(preview_briefing(db, org_id=principal.org_id, project=project, area=area, scene_code=scene_code))


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


@router.get("/{briefing_id}/document")
def briefing_view(
    briefing_id: uuid.UUID,
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    """Rendered briefing. Unpublished cited products are omitted, not drawn."""
    principal.require("briefing.read")
    row = _get(db, briefing_id, principal.org_id)
    if "admin" not in principal.roles and "duty_officer" not in principal.roles and row.status != "published":
        raise APIError(404, "not_found", "Briefing not found")
    return ok(briefing_document(db, row))


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
    _require_published_products(db, principal.org_id, row.product_ids)
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
