"""P0/P1 models: areas, data assets, product layers, time fields, audit trigger.

Revision ID: 0002_p0_p1
Revises: 0001_initial
Create Date: 2026-11-14
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0002_p0_p1"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def _uuid():
    return sa.Uuid()


def _json():
    return sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def _ts():
    return sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "areas",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("org_id", _uuid(), sa.ForeignKey("organizations.id"), nullable=False, index=True),
        sa.Column("project_id", _uuid(), sa.ForeignKey("projects.id"), nullable=False, index=True),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("is_pilot", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("timezone", sa.String(64), nullable=False, server_default="Asia/Shanghai"),
        sa.Column("aoi_geojson", _json(), nullable=True),
        sa.Column("bbox_json", _json(), nullable=True),
        sa.Column("analysis_crs", sa.String(32), nullable=False, server_default="EPSG:4548"),
        sa.Column("exchange_crs", sa.String(32), nullable=False, server_default="EPSG:4490"),
        sa.Column("grid_res_m", sa.Integer(), nullable=False, server_default="10"),
        sa.Column("grid_origin_x", sa.Float(), nullable=False, server_default="0"),
        sa.Column("grid_origin_y", sa.Float(), nullable=False, server_default="0"),
        sa.Column("config_json", _json(), nullable=False),
        sa.Column("created_at", _ts(), nullable=False),
        sa.Column("updated_at", _ts(), nullable=False),
        sa.Column("deleted_at", _ts(), nullable=True),
        sa.UniqueConstraint("org_id", "code", name="uq_areas_org_code"),
    )
    op.create_table(
        "data_assets",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("org_id", _uuid(), sa.ForeignKey("organizations.id"), nullable=False, index=True),
        sa.Column("project_id", _uuid(), sa.ForeignKey("projects.id"), nullable=True, index=True),
        sa.Column("area_id", _uuid(), sa.ForeignKey("areas.id"), nullable=True, index=True),
        sa.Column("asset_code", sa.String(128), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("asset_type", sa.String(64), nullable=False),
        sa.Column("description", sa.String(4000), nullable=False, server_default=""),
        sa.Column("owner", sa.String(200), nullable=False, server_default=""),
        sa.Column("default_crs", sa.String(32), nullable=False, server_default="EPSG:4490"),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("created_at", _ts(), nullable=False),
        sa.Column("updated_at", _ts(), nullable=False),
        sa.Column("deleted_at", _ts(), nullable=True),
        sa.UniqueConstraint("org_id", "asset_code", name="uq_data_assets_org_code"),
    )
    op.create_table(
        "data_asset_versions",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("org_id", _uuid(), sa.ForeignKey("organizations.id"), nullable=False, index=True),
        sa.Column("asset_id", _uuid(), sa.ForeignKey("data_assets.id"), nullable=False, index=True),
        sa.Column("version_no", sa.String(64), nullable=False),
        sa.Column("valid_from", _ts(), nullable=False),
        sa.Column("valid_to", _ts(), nullable=True),
        sa.Column("applicable_area_geojson", _json(), nullable=True),
        sa.Column("applicable_area_name", sa.String(200), nullable=False, server_default=""),
        sa.Column("review_status", sa.String(32), nullable=False, server_default="draft"),
        sa.Column("reviewer_id", _uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("reviewed_at", _ts(), nullable=True),
        sa.Column("review_comment", sa.String(2000), nullable=False, server_default=""),
        sa.Column("source", sa.String(200), nullable=False, server_default=""),
        sa.Column("algorithm_profile_id", sa.String(128), nullable=False, server_default=""),
        sa.Column("spatial_res_m", sa.Float(), nullable=True),
        sa.Column("crs", sa.String(32), nullable=False, server_default="EPSG:4490"),
        sa.Column("gsd_note", sa.String(500), nullable=False, server_default=""),
        sa.Column("checksum", sa.String(128), nullable=False, server_default=""),
        sa.Column("byte_size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("storage_uri", sa.String(1000), nullable=False, server_default=""),
        sa.Column("preview_uri", sa.String(1000), nullable=False, server_default=""),
        sa.Column("schema_json", _json(), nullable=False),
        sa.Column("lineage_json", _json(), nullable=False),
        sa.Column("created_by", _uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", _ts(), nullable=False),
        sa.Column("updated_at", _ts(), nullable=False),
        sa.Column("deleted_at", _ts(), nullable=True),
        sa.UniqueConstraint("asset_id", "version_no", name="uq_data_asset_versions_no"),
    )
    op.create_table(
        "algo_profiles",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("org_id", _uuid(), sa.ForeignKey("organizations.id"), nullable=True, index=True),
        sa.Column("scene_id", _uuid(), sa.ForeignKey("scenes.id"), nullable=True),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("version", sa.String(32), nullable=False, server_default="1.0.0"),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("params_json", _json(), nullable=False),
        sa.Column("created_at", _ts(), nullable=False),
        sa.Column("updated_at", _ts(), nullable=False),
        sa.Column("deleted_at", _ts(), nullable=True),
        sa.UniqueConstraint("org_id", "code", "version", name="uq_algo_profiles_org_code_ver"),
    )
    op.create_table(
        "processing_jobs",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("org_id", _uuid(), sa.ForeignKey("organizations.id"), nullable=False, index=True),
        sa.Column("task_id", _uuid(), sa.ForeignKey("tasks.id"), nullable=False, index=True),
        sa.Column("engine_job_id", sa.String(128), nullable=False, server_default=""),
        sa.Column("status", sa.String(32), nullable=False, server_default="accepted"),
        sa.Column("step", sa.String(64), nullable=False, server_default=""),
        sa.Column("progress_json", _json(), nullable=False),
        sa.Column("error_code", sa.String(64), nullable=False, server_default=""),
        sa.Column("log_uri", sa.String(1000), nullable=False, server_default=""),
        sa.Column("started_at", _ts(), nullable=True),
        sa.Column("finished_at", _ts(), nullable=True),
        sa.Column("created_at", _ts(), nullable=False),
        sa.Column("updated_at", _ts(), nullable=False),
    )
    op.create_table(
        "product_layers",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("org_id", _uuid(), sa.ForeignKey("organizations.id"), nullable=False, index=True),
        sa.Column("product_id", _uuid(), sa.ForeignKey("products.id"), nullable=False, index=True),
        sa.Column("layer_key", sa.String(64), nullable=False),
        sa.Column("media_type", sa.String(128), nullable=False, server_default="application/octet-stream"),
        sa.Column("storage_uri", sa.String(1000), nullable=False, server_default=""),
        sa.Column("metadata_json", _json(), nullable=False),
        sa.Column("created_at", _ts(), nullable=False),
        sa.Column("updated_at", _ts(), nullable=False),
        sa.UniqueConstraint("product_id", "layer_key", name="uq_product_layers_key"),
    )
    op.create_table(
        "impact_stats",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("org_id", _uuid(), sa.ForeignKey("organizations.id"), nullable=False, index=True),
        sa.Column("product_id", _uuid(), sa.ForeignKey("products.id"), nullable=False, index=True),
        sa.Column("object_type", sa.String(64), nullable=False),
        sa.Column("object_id", sa.String(128), nullable=False, server_default=""),
        sa.Column("object_name", sa.String(200), nullable=False, server_default=""),
        sa.Column("metric", sa.String(64), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("unit", sa.String(32), nullable=False, server_default=""),
        sa.Column("scope", sa.String(32), nullable=False, server_default="default"),
        sa.Column("extra_json", _json(), nullable=False),
        sa.Column("created_at", _ts(), nullable=False),
        sa.Column("updated_at", _ts(), nullable=False),
    )

    op.add_column("service_accounts", sa.Column("key_prefix", sa.String(32), nullable=False, server_default=""))
    op.add_column("service_accounts", sa.Column("revoked_at", _ts(), nullable=True))

    for col in (
        sa.Column("area_id", _uuid(), sa.ForeignKey("areas.id"), nullable=True),
        sa.Column("progress_json", _json(), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=False, server_default=""),
        sa.Column("log_uri", sa.String(1000), nullable=False, server_default=""),
        sa.Column("idempotency_key", sa.String(200), nullable=True),
        sa.Column("algo_profile_id", sa.String(128), nullable=False, server_default=""),
        sa.Column("baseline_version_id", _uuid(), sa.ForeignKey("data_asset_versions.id"), nullable=True),
        sa.Column("data_ready_at", _ts(), nullable=True),
        sa.Column("submitted_at", _ts(), nullable=True),
        sa.Column("processed_at", _ts(), nullable=True),
    ):
        op.add_column("tasks", col)
    op.create_index("ix_tasks_area_id", "tasks", ["area_id"])
    op.create_unique_constraint("uq_tasks_org_idempotency", "tasks", ["org_id", "idempotency_key"])

    for col in (
        sa.Column("area_id", _uuid(), sa.ForeignKey("areas.id"), nullable=True),
        sa.Column("data_asset_id", _uuid(), sa.ForeignKey("data_assets.id"), nullable=True),
        sa.Column("baseline_version_id", _uuid(), sa.ForeignKey("data_asset_versions.id"), nullable=True),
        sa.Column("flood_event_status", sa.String(32), nullable=False, server_default="none"),
        sa.Column("extracted_water_ha", sa.Float(), nullable=True),
        sa.Column("water_current_ha", sa.Float(), nullable=True),
        sa.Column("flood_event_ha", sa.Float(), nullable=True),
        sa.Column("lowconf_ha", sa.Float(), nullable=True),
        sa.Column("suggested_target_minutes", sa.Integer(), nullable=False, server_default="240"),
        sa.Column("data_ready_at", _ts(), nullable=True),
        sa.Column("processed_at", _ts(), nullable=True),
        sa.Column("reject_reason", sa.String(2000), nullable=False, server_default=""),
        sa.Column("re_qc_required", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("supersedes_id", _uuid(), sa.ForeignKey("products.id"), nullable=True),
    ):
        op.add_column("products", col)

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            """
            CREATE OR REPLACE FUNCTION audit_logs_immutable() RETURNS trigger AS $$
            BEGIN
              RAISE EXCEPTION 'audit_logs are append-only';
            END;
            $$ LANGUAGE plpgsql;
            """
        )
        op.execute(
            """
            DROP TRIGGER IF EXISTS audit_logs_no_mutate ON audit_logs;
            CREATE TRIGGER audit_logs_no_mutate
            BEFORE UPDATE OR DELETE ON audit_logs
            FOR EACH ROW EXECUTE FUNCTION audit_logs_immutable();
            """
        )
        op.execute("REVOKE UPDATE, DELETE ON audit_logs FROM PUBLIC")


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS audit_logs_no_mutate ON audit_logs")
        op.execute("DROP FUNCTION IF EXISTS audit_logs_immutable()")
    for col in [
        "supersedes_id",
        "re_qc_required",
        "reject_reason",
        "processed_at",
        "data_ready_at",
        "suggested_target_minutes",
        "lowconf_ha",
        "flood_event_ha",
        "water_current_ha",
        "extracted_water_ha",
        "flood_event_status",
        "baseline_version_id",
        "data_asset_id",
        "area_id",
    ]:
        op.drop_column("products", col)
    op.drop_constraint("uq_tasks_org_idempotency", "tasks", type_="unique")
    op.drop_index("ix_tasks_area_id", table_name="tasks")
    for col in [
        "processed_at",
        "submitted_at",
        "data_ready_at",
        "baseline_version_id",
        "algo_profile_id",
        "idempotency_key",
        "log_uri",
        "error_code",
        "progress_json",
        "area_id",
    ]:
        op.drop_column("tasks", col)
    op.drop_column("service_accounts", "revoked_at")
    op.drop_column("service_accounts", "key_prefix")
    op.drop_table("impact_stats")
    op.drop_table("product_layers")
    op.drop_table("processing_jobs")
    op.drop_table("algo_profiles")
    op.drop_table("data_asset_versions")
    op.drop_table("data_assets")
    op.drop_table("areas")
