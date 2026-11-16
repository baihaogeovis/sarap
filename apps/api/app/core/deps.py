from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

import jwt
from fastapi import Depends, Header
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db
from app.core.responses import APIError
from app.core.security import decode_token, verify_password
from app.models import Membership, Permission, Role, RolePermission, ServiceAccount, User
from app.services.permissions import V1_SURFACE_ROLES


@dataclass
class Principal:
    typ: str  # user | service
    id: uuid.UUID
    org_id: uuid.UUID
    email: str | None
    name: str
    roles: list[str] = field(default_factory=list)
    permissions: set[str] = field(default_factory=set)
    memberships: list[Membership] = field(default_factory=list)

    def has(self, code: str) -> bool:
        return code in self.permissions

    def require(self, *codes: str) -> None:
        if not any(self.has(code) for code in codes):
            raise APIError(403, "forbidden", "Current role is not allowed to perform this action")


def _permissions_for_roles(db: Session, role_codes: list[str]) -> set[str]:
    if not role_codes:
        return set()
    rows = (
        db.query(Permission.code)
        .join(RolePermission, RolePermission.permission_id == Permission.id)
        .join(Role, Role.id == RolePermission.role_id)
        .filter(Role.code.in_(role_codes))
        .all()
    )
    return {row[0] for row in rows}


def load_user_principal(db: Session, user_id: uuid.UUID, org_id: uuid.UUID | None = None) -> Principal:
    user = db.get(User, user_id)
    if user is None or user.status != "active" or user.deleted_at is not None:
        raise APIError(401, "unauthorized", "User is not active")
    memberships = db.query(Membership).filter(Membership.user_id == user.id).all()
    if not memberships:
        raise APIError(403, "forbidden", "User has no memberships")
    if org_id is None:
        org_id = memberships[0].org_id
    org_memberships = [m for m in memberships if m.org_id == org_id]
    if not org_memberships:
        raise APIError(403, "forbidden", "User is not a member of this organization")
    roles = list({m.role_code for m in org_memberships})
    return Principal(
        typ="user",
        id=user.id,
        org_id=org_id,
        email=user.email,
        name=user.name,
        roles=roles,
        permissions=_permissions_for_roles(db, roles),
        memberships=org_memberships,
    )


def load_service_principal(db: Session, account: ServiceAccount) -> Principal:
    if account.status != "active" or account.deleted_at is not None or account.revoked_at is not None:
        raise APIError(401, "unauthorized", "Service account is not active")
    return Principal(
        typ="service",
        id=account.id,
        org_id=account.org_id,
        email=None,
        name=account.name,
        roles=["service"],
        permissions=set(account.scopes or []),
    )


def authenticate_api_key(db: Session, raw: str) -> Principal:
    prefix = raw.split(".", 1)[0] if "." in raw else raw[:16]
    # Try prefix lookup first, then scan a small set of org keys is avoided by prefix index.
    candidates = (
        db.query(ServiceAccount)
        .filter(ServiceAccount.key_prefix == prefix, ServiceAccount.deleted_at.is_(None))
        .all()
    )
    if not candidates:
        # fallback: client_id may be the prefix
        candidates = (
            db.query(ServiceAccount)
            .filter(ServiceAccount.client_id == prefix, ServiceAccount.deleted_at.is_(None))
            .all()
        )
    for account in candidates:
        if verify_password(raw, account.secret_hash):
            return load_service_principal(db, account)
    raise APIError(401, "unauthorized", "Invalid API key")


def get_current_principal(
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    db: Session = Depends(get_db),
) -> Principal:
    if x_api_key:
        return authenticate_api_key(db, x_api_key)
    if not authorization or not authorization.lower().startswith("bearer "):
        raise APIError(401, "unauthorized", "Missing bearer token")
    token = authorization.split(" ", 1)[1].strip()
    try:
        payload: dict[str, Any] = decode_token(token)
    except jwt.ExpiredSignatureError as exc:
        raise APIError(401, "unauthorized", "Access token has expired") from exc
    except jwt.PyJWTError as exc:
        raise APIError(401, "unauthorized", "Invalid access token") from exc
    if payload.get("typ") not in {"access", "user", "service"}:
        # access tokens carry typ=access plus a principal typ in "ptype"
        if payload.get("typ") == "refresh":
            raise APIError(401, "unauthorized", "Refresh token cannot be used as an access token")
    ptype = payload.get("ptype") or ("service" if payload.get("typ") == "service" else "user")
    if ptype == "service":
        account = db.get(ServiceAccount, uuid.UUID(payload["sub"]))
        if account is None:
            raise APIError(401, "unauthorized", "Service account is not active")
        return load_service_principal(db, account)
    org_claim = payload.get("org_id")
    org_id = uuid.UUID(org_claim) if org_claim else None
    return load_user_principal(db, uuid.UUID(payload["sub"]), org_id)


def require_permissions(*codes: str):
    def dependency(principal: Principal = Depends(get_current_principal)) -> Principal:
        principal.require(*codes)
        return principal

    return dependency


def require_v1_role(*roles: str):
    allowed = roles or V1_SURFACE_ROLES

    def dependency(principal: Principal = Depends(get_current_principal)) -> Principal:
        if not any(role in principal.roles for role in allowed):
            raise APIError(403, "forbidden", "Current role is not allowed to perform this action")
        return principal

    return dependency


def verify_internal_token(x_internal_token: str | None = Header(default=None, alias="X-Internal-Token")) -> None:
    expected = settings.internal_token
    if not x_internal_token or x_internal_token != expected:
        raise APIError(401, "unauthorized", "Invalid internal token")


def verify_internal_or_service(
    x_internal_token: str | None = Header(default=None, alias="X-Internal-Token"),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> Principal | None:
    """Allow the shared internal token or a service principal with api.invoke."""
    if x_internal_token and x_internal_token == settings.internal_token:
        return None
    if x_api_key or (authorization and authorization.lower().startswith("bearer ")):
        principal = get_current_principal(authorization=authorization, x_api_key=x_api_key, db=db)
        if principal.typ != "service" or not principal.has("api.invoke"):
            raise APIError(403, "forbidden", "Internal endpoints require a service account with api.invoke")
        return principal
    raise APIError(401, "unauthorized", "Invalid internal token or API key")
