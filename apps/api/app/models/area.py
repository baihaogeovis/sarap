from __future__ import annotations

import uuid

from sqlalchemy import JSON, Boolean, Float, ForeignKey, Integer, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IDMixin, SoftDeleteMixin, TimestampMixin


class Area(IDMixin, TimestampMixin, SoftDeleteMixin, Base):
    """Region is the primary spatial object. Pilot settings live in config_json.

    Do not treat a Pilot table as the region, and do not hardcode a basin name.
    """

    __tablename__ = "areas"
    __table_args__ = (UniqueConstraint("org_id", "code", name="uq_areas_org_code"),)

    org_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("organizations.id"), nullable=False, index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("projects.id"), nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    is_pilot: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Shanghai", nullable=False)
    aoi_geojson: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    bbox_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    analysis_crs: Mapped[str] = mapped_column(String(32), default="EPSG:4548", nullable=False)
    exchange_crs: Mapped[str] = mapped_column(String(32), default="EPSG:4490", nullable=False)
    grid_res_m: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    grid_origin_x: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    grid_origin_y: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    # Pilot configuration item on the area (algo profile, baselines, publish flags, …).
    config_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
