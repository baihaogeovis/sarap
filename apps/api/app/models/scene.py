from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String, UniqueConstraint, Uuid
from sqlalchemy.dialects.sqlite import JSON as SQLITE_JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IDMixin, SoftDeleteMixin, TimestampMixin


class Scene(IDMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "scenes"

    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(String(2000), default="", nullable=False)
    version: Mapped[str] = mapped_column(String(32), default="1.0.0", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="registered", nullable=False)
    manifest_json: Mapped[dict] = mapped_column(JSON().with_variant(SQLITE_JSON(), "sqlite"), default=dict, nullable=False)


class SceneActivation(IDMixin, TimestampMixin, Base):
    __tablename__ = "scene_activations"
    __table_args__ = (UniqueConstraint("project_id", "scene_id", name="uq_scene_activations_project_scene"),)

    org_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("organizations.id"), nullable=False, index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("projects.id"), nullable=False, index=True)
    scene_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("scenes.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="enabled", nullable=False)
    config_json: Mapped[dict] = mapped_column(JSON().with_variant(SQLITE_JSON(), "sqlite"), default=dict, nullable=False)
    activated_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"), nullable=True)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
