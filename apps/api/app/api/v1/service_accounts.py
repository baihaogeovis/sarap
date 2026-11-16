from __future__ import annotations

import secrets
import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import Principal, get_current_principal
from app.core.responses import APIError, ok
from app.core.security import hash_password
from app.models import ServiceAccount
from app.models.base import utcnow
from app.schemas.common import ServiceAccountIn, ServiceAccountOut
from app.services import audit

router = APIRouter(prefix="/service-accounts", tags=["service-accounts"])


def _generate_key(client_id: str) -> tuple[str, str, str]:
    secret = secrets.token_urlsafe(32)
    raw = f"{client_id}.{secret}"
    return raw, client_id, hash_password(raw)


@router.get("")
def list_accounts(principal: Principal = Depends(get_current_principal), db: Session = Depends(get_db)):
    principal.require("org.manage", "member.manage")
    rows = (
        db.query(ServiceAccount)
        .filter(ServiceAccount.org_id == principal.org_id, ServiceAccount.deleted_at.is_(None))
        .order_by(ServiceAccount.created_at)
        .all()
    )
    return ok([ServiceAccountOut.model_validate(r).model_dump(mode="json") for r in rows])


@router.post("")
def create_account(
    body: ServiceAccountIn,
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    principal.require("org.manage", "member.manage")
    client_id = body.client_id or f"sak_{secrets.token_hex(4)}"
    exists = (
        db.query(ServiceAccount)
        .filter(ServiceAccount.org_id == principal.org_id, ServiceAccount.client_id == client_id)
        .first()
    )
    if exists:
        raise APIError(409, "conflict", "client_id already exists")
    raw, prefix, hashed = _generate_key(client_id)
    row = ServiceAccount(
        org_id=principal.org_id,
        project_id=body.project_id,
        client_id=client_id,
        secret_hash=hashed,
        name=body.name,
        scopes=body.scopes or ["api.invoke"],
        key_prefix=prefix,
        status="active",
    )
    db.add(row)
    db.flush()
    audit.record(
        db,
        actor_type=principal.typ,
        actor_id=principal.id,
        action="service_account.create",
        resource_type="service_account",
        resource_id=str(row.id),
        org_id=principal.org_id,
        after={"client_id": client_id, "scopes": row.scopes},
    )
    db.commit()
    db.refresh(row)
    data = ServiceAccountOut.model_validate(row).model_dump(mode="json")
    data["api_key"] = raw  # plaintext only once
    return ok(data, status_code=201)


@router.post("/{account_id}/revoke")
def revoke_account(
    account_id: uuid.UUID,
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    principal.require("org.manage", "member.manage")
    row = db.get(ServiceAccount, account_id)
    if row is None or row.org_id != principal.org_id:
        raise APIError(404, "not_found", "Service account not found")
    row.status = "revoked"
    row.revoked_at = utcnow()
    audit.record(
        db,
        actor_type=principal.typ,
        actor_id=principal.id,
        action="service_account.revoke",
        resource_type="service_account",
        resource_id=str(row.id),
        org_id=principal.org_id,
    )
    db.commit()
    db.refresh(row)
    return ok(ServiceAccountOut.model_validate(row).model_dump(mode="json"))
