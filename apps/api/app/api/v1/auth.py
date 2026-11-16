from __future__ import annotations

import jwt
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.v1.serializers import user_out
from app.core.config import settings
from app.core.db import get_db
from app.core.deps import Principal, get_current_principal, load_user_principal
from app.core.responses import APIError, ok
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    verify_password,
)
from app.models import User
from app.schemas.common import LoginIn, RefreshIn, TokenOut

router = APIRouter(prefix="/auth", tags=["auth"])


def _tokens(principal: Principal) -> TokenOut:
    claims = {
        "sub": str(principal.id),
        "ptype": principal.typ,
        "org_id": str(principal.org_id),
        "roles": principal.roles,
        "permissions": sorted(principal.permissions),
    }
    return TokenOut(
        access_token=create_access_token(claims),
        refresh_token=create_refresh_token({"sub": str(principal.id), "ptype": principal.typ, "org_id": str(principal.org_id)}),
        expires_in=settings.access_token_minutes * 60,
    )


@router.post("/login")
def login(body: LoginIn, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == body.email, User.deleted_at.is_(None)).one_or_none()
    if user is None or not verify_password(body.password, user.password_hash):
        raise APIError(401, "unauthorized", "Invalid email or password")
    if user.status != "active":
        raise APIError(401, "unauthorized", "User is not active")
    principal = load_user_principal(db, user.id)
    tokens = _tokens(principal)
    return ok({"tokens": tokens.model_dump(), "user": user_out(user, principal).model_dump(mode="json")})


@router.post("/refresh")
def refresh(body: RefreshIn, db: Session = Depends(get_db)):
    try:
        payload = decode_token(body.refresh_token)
    except jwt.PyJWTError as exc:
        raise APIError(401, "unauthorized", "Invalid refresh token") from exc
    if payload.get("typ") != "refresh":
        raise APIError(401, "unauthorized", "Invalid refresh token")
    principal = load_user_principal(db, __import__("uuid").UUID(payload["sub"]))
    return ok(_tokens(principal).model_dump())


@router.get("/me")
def me(principal: Principal = Depends(get_current_principal), db: Session = Depends(get_db)):
    if principal.typ == "service":
        return ok(
            {
                "id": str(principal.id),
                "typ": "service",
                "name": principal.name,
                "org_id": str(principal.org_id),
                "roles": principal.roles,
                "permissions": sorted(principal.permissions),
            }
        )
    user = db.get(User, principal.id)
    if user is None:
        raise APIError(401, "unauthorized", "User not found")
    return ok(user_out(user, principal).model_dump(mode="json"))
