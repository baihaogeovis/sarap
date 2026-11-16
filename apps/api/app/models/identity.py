from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IDMixin, SoftDeleteMixin, TimestampMixin


class Organization(IDMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "organizations"

    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)


class Project(IDMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "projects"
    __table_args__ = (UniqueConstraint("org_id", "code", name="uq_projects_org_code"),)

    org_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("organizations.id"), nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    # Analysis CRS for official rasters/stats. Demo seed uses EPSG:4548 (see GIS spec §12).
    default_crs: Mapped[str] = mapped_column(String(32), default="EPSG:4548", nullable=False)
    bbox_json: Mapped[dict | None] = mapped_column(type_=__import__("sqlalchemy").JSON, nullable=True)
    aoi_wkt: Mapped[str | None] = mapped_column(String(4000), nullable=True)


class User(IDMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(254), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)


class ServiceAccount(IDMixin, TimestampMixin, SoftDeleteMixin, Base):
    """SERVICE principal — not a flag on the user table."""

    __tablename__ = "service_accounts"
    __table_args__ = (UniqueConstraint("org_id", "client_id", name="uq_service_accounts_org_client"),)

    org_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("organizations.id"), nullable=False, index=True)
    project_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("projects.id"), nullable=True)
    client_id: Mapped[str] = mapped_column(String(128), nullable=False)
    secret_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    scopes: Mapped[list] = mapped_column(type_=__import__("sqlalchemy").JSON, default=list, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rate_limit_rpm: Mapped[int] = mapped_column(default=60, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    key_prefix: Mapped[str] = mapped_column(String(32), default="", nullable=False, index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Membership(IDMixin, TimestampMixin, Base):
    __tablename__ = "memberships"
    __table_args__ = (
        UniqueConstraint("user_id", "scope_type", "scope_id", name="uq_memberships_user_scope"),
    )

    org_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("organizations.id"), nullable=False, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), nullable=False, index=True)
    scope_type: Mapped[str] = mapped_column(String(32), nullable=False)  # organization | project
    scope_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    role_code: Mapped[str] = mapped_column(String(64), nullable=False)
