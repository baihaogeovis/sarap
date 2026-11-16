from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    event,
)
from sqlalchemy.orm import Mapped, ORMExecuteState, Session, mapped_column

from app.models.base import Base, IDMixin, SoftDeleteMixin, TimestampMixin, utcnow


class AlgoProfile(IDMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "algo_profiles"
    __table_args__ = (UniqueConstraint("org_id", "code", "version", name="uq_algo_profiles_org_code_ver"),)

    org_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("organizations.id"), nullable=True, index=True)
    scene_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("scenes.id"), nullable=True)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    version: Mapped[str] = mapped_column(String(32), default="1.0.0", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    params_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class Task(IDMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "tasks"
    __table_args__ = (
        UniqueConstraint("org_id", "code", name="uq_tasks_org_code"),
        UniqueConstraint("org_id", "idempotency_key", name="uq_tasks_org_idempotency"),
    )

    org_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("organizations.id"), nullable=False, index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("projects.id"), nullable=False, index=True)
    area_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("areas.id"), nullable=True, index=True)
    scene_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("scenes.id"), nullable=True)
    scene_code: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    code: Mapped[str] = mapped_column(String(128), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    task_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="queued", nullable=False, index=True)
    priority: Mapped[str] = mapped_column(String(32), default="normal", nullable=False)
    emergency: Mapped[bool] = mapped_column(default=False, nullable=False)
    params_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    progress: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    progress_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    step: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    error_message: Mapped[str] = mapped_column(Text, default="", nullable=False)
    error_code: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    log_uri: Mapped[str] = mapped_column(String(1000), default="", nullable=False)
    engine_job_id: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    result_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    assignee_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    algo_profile_id: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    baseline_version_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("data_asset_versions.id"), nullable=True
    )
    # Timestamps are stored in UTC. Display should use Asia/Shanghai.
    data_ready_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Imaging time and Sentinel-1 PRODUCT-ID (not platform scene_id/scene_code).
    acquisition_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    acquisition_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    s1_product_id: Mapped[str] = mapped_column(String(200), default="", nullable=False)


class ProcessingJob(IDMixin, TimestampMixin, Base):
    """Engine-side job record aligned with a platform Task."""

    __tablename__ = "processing_jobs"

    org_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("organizations.id"), nullable=False, index=True)
    task_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tasks.id"), nullable=False, index=True)
    engine_job_id: Mapped[str] = mapped_column(String(128), default="", nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), default="accepted", nullable=False)
    step: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    progress_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    error_code: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    log_uri: Mapped[str] = mapped_column(String(1000), default="", nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Product(IDMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "products"
    __table_args__ = (UniqueConstraint("org_id", "code", "version", name="uq_products_org_code_version"),)

    org_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("organizations.id"), nullable=False, index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("projects.id"), nullable=False, index=True)
    area_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("areas.id"), nullable=True, index=True)
    scene_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("scenes.id"), nullable=True)
    scene_code: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    task_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("tasks.id"), nullable=True)
    imagery_dataset_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("datasets.id"), nullable=True)
    baseline_asset_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("baseline_assets.id"), nullable=True)
    data_asset_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("data_assets.id"), nullable=True)
    baseline_version: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    baseline_version_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("data_asset_versions.id"), nullable=True
    )
    engine_name: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    engine_params_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    code: Mapped[str] = mapped_column(String(200), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    product_type: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    # draft | pending_qc | published | withdrawn  (pending_qc == pending_review)
    status: Mapped[str] = mapped_column(String(32), default="draft", nullable=False, index=True)
    storage_uri: Mapped[str] = mapped_column(String(1000), default="", nullable=False)
    artifacts_json: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    # none | baseline_missing | computed
    flood_event_status: Mapped[str] = mapped_column(String(32), default="none", nullable=False)
    extracted_water_ha: Mapped[float | None] = mapped_column(Float, nullable=True)
    water_current_ha: Mapped[float | None] = mapped_column(Float, nullable=True)
    flood_event_ha: Mapped[float | None] = mapped_column(Float, nullable=True)
    lowconf_ha: Mapped[float | None] = mapped_column(Float, nullable=True)
    suggested_target_minutes: Mapped[int] = mapped_column(Integer, default=240, nullable=False)
    data_ready_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    acquisition_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    acquisition_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    s1_product_id: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    withdraw_reason: Mapped[str] = mapped_column(String(1000), default="", nullable=False)
    review_comment: Mapped[str] = mapped_column(String(2000), default="", nullable=False)
    reject_reason: Mapped[str] = mapped_column(String(2000), default="", nullable=False)
    re_qc_required: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    supersedes_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("products.id"), nullable=True)


class ProductLayer(IDMixin, TimestampMixin, Base):
    __tablename__ = "product_layers"
    __table_args__ = (UniqueConstraint("product_id", "layer_key", name="uq_product_layers_key"),)

    org_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("organizations.id"), nullable=False, index=True)
    product_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("products.id"), nullable=False, index=True)
    layer_key: Mapped[str] = mapped_column(String(64), nullable=False)
    media_type: Mapped[str] = mapped_column(String(128), default="application/octet-stream", nullable=False)
    storage_uri: Mapped[str] = mapped_column(String(1000), default="", nullable=False)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class ImpactStat(IDMixin, TimestampMixin, Base):
    """Long-table impact statistics. P0 only stores area metrics; P1 cross stats only when assets exist."""

    __tablename__ = "impact_stats"

    org_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("organizations.id"), nullable=False, index=True)
    product_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("products.id"), nullable=False, index=True)
    object_type: Mapped[str] = mapped_column(String(64), nullable=False)
    object_id: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    object_name: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    metric: Mapped[str] = mapped_column(String(64), nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    scope: Mapped[str] = mapped_column(String(32), default="default", nullable=False)
    extra_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class Briefing(IDMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "briefings"
    __table_args__ = (UniqueConstraint("org_id", "code", name="uq_briefings_org_code"),)

    org_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("organizations.id"), nullable=False, index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("projects.id"), nullable=False, index=True)
    scene_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("scenes.id"), nullable=True)
    scene_code: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    code: Mapped[str] = mapped_column(String(128), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="draft", nullable=False)
    period_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    content_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    product_ids: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AuditLogImmutableError(RuntimeError):
    """Raised when code attempts to update or delete an audit log row."""


class AuditLog(IDMixin, Base):
    __tablename__ = "audit_logs"

    org_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("organizations.id"), nullable=True, index=True)
    project_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    actor_type: Mapped[str] = mapped_column(String(32), nullable=False)  # user | service
    actor_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(64), nullable=False)
    request_id: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    before_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    after_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


@event.listens_for(AuditLog, "before_update")
def _audit_no_update(mapper, connection, target) -> None:  # noqa: ANN001
    raise AuditLogImmutableError("audit_logs are append-only; updates are forbidden")


@event.listens_for(AuditLog, "before_delete")
def _audit_no_delete(mapper, connection, target) -> None:  # noqa: ANN001
    raise AuditLogImmutableError("audit_logs are append-only; deletes are forbidden")


@event.listens_for(Session, "do_orm_execute")
def _audit_block_bulk(execute_state: ORMExecuteState) -> None:
    if not (execute_state.is_update or execute_state.is_delete):
        return
    mapper = execute_state.bind_mapper
    if mapper is not None and mapper.class_ is AuditLog:
        raise AuditLogImmutableError("audit_logs are append-only; updates and deletes are forbidden")
