from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.v1.serializers import project_out
from app.core.db import get_db
from app.core.deps import Principal, get_current_principal
from app.core.responses import APIError, ok
from app.models import Membership, Organization, Project, User
from app.schemas.common import MemberIn, MemberOut, ProjectIn
from app.services import audit
from app.services.permissions import V1_SURFACE_ROLES

router = APIRouter(tags=["projects"])


def _org(db: Session, org_id: uuid.UUID) -> Organization:
    org = db.get(Organization, org_id)
    if org is None:
        raise APIError(404, "not_found", "Organization not found")
    return org


@router.get("/orgs")
def list_orgs(principal: Principal = Depends(get_current_principal), db: Session = Depends(get_db)):
    org = _org(db, principal.org_id)
    return ok([{"id": str(org.id), "code": org.code, "name": org.name, "status": org.status}])


@router.get("/projects")
def list_projects(principal: Principal = Depends(get_current_principal), db: Session = Depends(get_db)):
    rows = (
        db.query(Project)
        .filter(Project.org_id == principal.org_id, Project.deleted_at.is_(None))
        .order_by(Project.created_at)
        .all()
    )
    return ok([project_out(row).model_dump(mode="json") for row in rows])


@router.post("/projects")
def create_project(
    body: ProjectIn,
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    principal.require("project.manage")
    exists = (
        db.query(Project)
        .filter(Project.org_id == principal.org_id, Project.code == body.code, Project.deleted_at.is_(None))
        .first()
    )
    if exists:
        raise APIError(409, "conflict", "A project with this code already exists in the organization")
    # org_id in the body is ignored deliberately.
    row = Project(
        org_id=principal.org_id,
        code=body.code,
        name=body.name,
        default_crs=body.default_crs,
        bbox_json=body.bbox_json,
        aoi_wkt=body.aoi_wkt,
    )
    db.add(row)
    db.flush()
    audit.record(
        db,
        actor_type=principal.typ,
        actor_id=principal.id,
        action="project.create",
        resource_type="project",
        resource_id=str(row.id),
        org_id=principal.org_id,
        project_id=row.id,
        after={"code": row.code, "default_crs": row.default_crs},
    )
    db.commit()
    db.refresh(row)
    return ok(project_out(row).model_dump(mode="json"), status_code=201)


@router.get("/projects/{project_id}")
def get_project(
    project_id: uuid.UUID,
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    row = db.get(Project, project_id)
    if row is None or row.org_id != principal.org_id or row.deleted_at is not None:
        raise APIError(404, "not_found", "Project not found")
    return ok(project_out(row).model_dump(mode="json"))


@router.patch("/projects/{project_id}")
def update_project(
    project_id: uuid.UUID,
    body: ProjectIn,
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    principal.require("project.manage")
    row = db.get(Project, project_id)
    if row is None or row.org_id != principal.org_id or row.deleted_at is not None:
        raise APIError(404, "not_found", "Project not found")
    row.name = body.name
    row.default_crs = body.default_crs
    row.bbox_json = body.bbox_json
    row.aoi_wkt = body.aoi_wkt
    db.commit()
    db.refresh(row)
    return ok(project_out(row).model_dump(mode="json"))


@router.get("/projects/{project_id}/members")
def list_members(
    project_id: uuid.UUID,
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    principal.require("member.manage", "project.manage", "task.read")
    row = db.get(Project, project_id)
    if row is None or row.org_id != principal.org_id:
        raise APIError(404, "not_found", "Project not found")
    members = (
        db.query(Membership)
        .filter(Membership.scope_type == "project", Membership.scope_id == project_id)
        .all()
    )
    return ok([MemberOut.model_validate(m).model_dump(mode="json") for m in members])


@router.post("/projects/{project_id}/members")
def add_member(
    project_id: uuid.UUID,
    body: MemberIn,
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    principal.require("member.manage")
    row = db.get(Project, project_id)
    if row is None or row.org_id != principal.org_id:
        raise APIError(404, "not_found", "Project not found")
    user = db.get(User, body.user_id)
    if user is None:
        raise APIError(404, "not_found", "User not found")
    if body.role_code not in V1_SURFACE_ROLES:
        raise APIError(403, "forbidden", "V1 API 只允许绑定 admin、duty_officer、readonly")
    membership = Membership(
        org_id=principal.org_id,
        user_id=body.user_id,
        scope_type="project",
        scope_id=project_id,
        role_code=body.role_code,
    )
    db.add(membership)
    audit.record(
        db,
        actor_type=principal.typ,
        actor_id=principal.id,
        action="member.add",
        resource_type="membership",
        resource_id=str(body.user_id),
        org_id=principal.org_id,
        project_id=project_id,
        after={"role_code": body.role_code},
    )
    db.commit()
    db.refresh(membership)
    return ok(MemberOut.model_validate(membership).model_dump(mode="json"), status_code=201)


@router.delete("/projects/{project_id}/members/{user_id}")
def remove_member(
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    principal.require("member.manage")
    membership = (
        db.query(Membership)
        .filter(
            Membership.scope_type == "project",
            Membership.scope_id == project_id,
            Membership.user_id == user_id,
            Membership.org_id == principal.org_id,
        )
        .one_or_none()
    )
    if membership is None:
        raise APIError(404, "not_found", "Membership not found")
    db.delete(membership)
    audit.record(
        db,
        actor_type=principal.typ,
        actor_id=principal.id,
        action="member.remove",
        resource_type="membership",
        resource_id=str(user_id),
        org_id=principal.org_id,
        project_id=project_id,
    )
    db.commit()
    return ok({"removed": True})
