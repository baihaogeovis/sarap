from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IDMixin, SoftDeleteMixin, TimestampMixin


class Dataset(IDMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "datasets"
    __table_args__ = (UniqueConstraint("org_id", "code", name="uq_datasets_org_code"),)

    org_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("organizations.id"), nullable=False, index=True)
    project_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("projects.id"), nullable=True, index=True)
    code: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    dataset_type: Mapped[str] = mapped_column(String(32), nullable=False)  # vector|raster|tabular|service
    source: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    format: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    crs: Mapped[str] = mapped_column(String(32), default="EPSG:4490", nullable=False)
    bbox_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    time_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    time_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    tags: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    storage_uri: Mapped[str] = mapped_column(String(1000), default="", nullable=False)
    checksum: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="available", nullable=False)
    scene_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("scenes.id"), nullable=True)
    # Sentinel-1 PRODUCT-ID; not the platform Scene.code (flood).
    s1_product_id: Mapped[str] = mapped_column(String(200), default="", nullable=False)


class BaselineAsset(IDMixin, TimestampMixin, SoftDeleteMixin, Base):
    """Versioned first-class baseline; not a task temp file."""

    __tablename__ = "baseline_assets"
    __table_args__ = (UniqueConstraint("org_id", "code", "version", name="uq_baselines_org_code_version"),)

    org_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("organizations.id"), nullable=False, index=True)
    project_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("projects.id"), nullable=True, index=True)
    dataset_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("datasets.id"), nullable=False)
    code: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    applicable_area_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    applicable_area_name: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    review_status: Mapped[str] = mapped_column(String(32), default="draft", nullable=False)
    reviewer_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_comment: Mapped[str] = mapped_column(String(2000), default="", nullable=False)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class DataAsset(IDMixin, TimestampMixin, SoftDeleteMixin, Base):
    """Platform data asset (baselines and reference layers). See GIS spec §5.2."""

    __tablename__ = "data_assets"
    __table_args__ = (UniqueConstraint("org_id", "asset_code", name="uq_data_assets_org_code"),)

    org_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("organizations.id"), nullable=False, index=True)
    project_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("projects.id"), nullable=True, index=True)
    area_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("areas.id"), nullable=True, index=True)
    asset_code: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    asset_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    description: Mapped[str] = mapped_column(String(4000), default="", nullable=False)
    owner: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    default_crs: Mapped[str] = mapped_column(String(32), default="EPSG:4490", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)


class DataAssetVersion(IDMixin, TimestampMixin, SoftDeleteMixin, Base):
    """Versioned payload of a data asset. review_status is independent of product.status."""

    __tablename__ = "data_asset_versions"
    __table_args__ = (UniqueConstraint("asset_id", "version_no", name="uq_data_asset_versions_no"),)

    org_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("organizations.id"), nullable=False, index=True)
    asset_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("data_assets.id"), nullable=False, index=True)
    version_no: Mapped[str] = mapped_column(String(64), nullable=False)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    applicable_area_geojson: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    applicable_area_name: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    # draft | pending_review | published | rejected | deprecated
    review_status: Mapped[str] = mapped_column(String(32), default="draft", nullable=False, index=True)
    reviewer_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_comment: Mapped[str] = mapped_column(String(2000), default="", nullable=False)
    source: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    algorithm_profile_id: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    spatial_res_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    crs: Mapped[str] = mapped_column(String(32), default="EPSG:4490", nullable=False)
    gsd_note: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    checksum: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    byte_size: Mapped[int] = mapped_column(default=0, nullable=False)
    storage_uri: Mapped[str] = mapped_column(String(1000), default="", nullable=False)
    preview_uri: Mapped[str] = mapped_column(String(1000), default="", nullable=False)
    schema_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    lineage_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"), nullable=True)
