"""Initial SARAP platform schema.

Revision ID: 0001_initial
Revises:
Create Date: 2026-11-14
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def _uuid():
    return sa.Uuid()


def _json():
    return sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def _ts():
    return sa.DateTime(timezone=True)


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS postgis")

    op.create_table(
        "organizations",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("code", sa.String(64), nullable=False, unique=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("created_at", _ts(), nullable=False),
        sa.Column("updated_at", _ts(), nullable=False),
        sa.Column("deleted_at", _ts(), nullable=True),
    )
    op.create_table(
        "roles",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("code", sa.String(64), nullable=False, unique=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.String(500), nullable=False, server_default=""),
        sa.Column("scope", sa.String(32), nullable=False, server_default="organization"),
        sa.Column("reserved", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", _ts(), nullable=False),
        sa.Column("updated_at", _ts(), nullable=False),
    )
    op.create_table(
        "permissions",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("code", sa.String(64), nullable=False, unique=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.String(500), nullable=False, server_default=""),
        sa.Column("created_at", _ts(), nullable=False),
        sa.Column("updated_at", _ts(), nullable=False),
    )
    op.create_table(
        "role_permissions",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("role_id", _uuid(), sa.ForeignKey("roles.id"), nullable=False),
        sa.Column("permission_id", _uuid(), sa.ForeignKey("permissions.id"), nullable=False),
        sa.UniqueConstraint("role_id", "permission_id", name="uq_role_permissions"),
    )
    op.create_table(
        "users",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("email", sa.String(254), nullable=False, unique=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("created_at", _ts(), nullable=False),
        sa.Column("updated_at", _ts(), nullable=False),
        sa.Column("deleted_at", _ts(), nullable=True),
    )
    op.create_table(
        "projects",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("org_id", _uuid(), sa.ForeignKey("organizations.id"), nullable=False, index=True),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("default_crs", sa.String(32), nullable=False, server_default="EPSG:4548"),
        sa.Column("bbox_json", _json(), nullable=True),
        sa.Column("aoi_wkt", sa.String(4000), nullable=True),
        sa.Column("created_at", _ts(), nullable=False),
        sa.Column("updated_at", _ts(), nullable=False),
        sa.Column("deleted_at", _ts(), nullable=True),
        sa.UniqueConstraint("org_id", "code", name="uq_projects_org_code"),
    )
    op.create_table(
        "service_accounts",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("org_id", _uuid(), sa.ForeignKey("organizations.id"), nullable=False, index=True),
        sa.Column("project_id", _uuid(), sa.ForeignKey("projects.id"), nullable=True),
        sa.Column("client_id", sa.String(128), nullable=False),
        sa.Column("secret_hash", sa.String(255), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("scopes", _json(), nullable=False),
        sa.Column("expires_at", _ts(), nullable=True),
        sa.Column("rate_limit_rpm", sa.Integer(), nullable=False, server_default="60"),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("key_prefix", sa.String(32), nullable=False, server_default=""),
        sa.Column("revoked_at", _ts(), nullable=True),
        sa.Column("created_at", _ts(), nullable=False),
        sa.Column("updated_at", _ts(), nullable=False),
        sa.Column("deleted_at", _ts(), nullable=True),
        sa.UniqueConstraint("org_id", "client_id", name="uq_service_accounts_org_client"),
    )
    op.create_table(
        "memberships",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("org_id", _uuid(), sa.ForeignKey("organizations.id"), nullable=False, index=True),
        sa.Column("user_id", _uuid(), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("scope_type", sa.String(32), nullable=False),
        sa.Column("scope_id", _uuid(), nullable=False),
        sa.Column("role_code", sa.String(64), nullable=False),
        sa.Column("created_at", _ts(), nullable=False),
        sa.Column("updated_at", _ts(), nullable=False),
        sa.UniqueConstraint("user_id", "scope_type", "scope_id", name="uq_memberships_user_scope"),
    )
    op.create_table(
        "scenes",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("code", sa.String(64), nullable=False, unique=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.String(2000), nullable=False, server_default=""),
        sa.Column("version", sa.String(32), nullable=False, server_default="1.0.0"),
        sa.Column("status", sa.String(32), nullable=False, server_default="registered"),
        sa.Column("manifest_json", _json(), nullable=False),
        sa.Column("created_at", _ts(), nullable=False),
        sa.Column("updated_at", _ts(), nullable=False),
        sa.Column("deleted_at", _ts(), nullable=True),
    )
    op.create_table(
        "scene_activations",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("org_id", _uuid(), sa.ForeignKey("organizations.id"), nullable=False, index=True),
        sa.Column("project_id", _uuid(), sa.ForeignKey("projects.id"), nullable=False, index=True),
        sa.Column("scene_id", _uuid(), sa.ForeignKey("scenes.id"), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="enabled"),
        sa.Column("config_json", _json(), nullable=False),
        sa.Column("activated_by", _uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("activated_at", _ts(), nullable=True),
        sa.Column("created_at", _ts(), nullable=False),
        sa.Column("updated_at", _ts(), nullable=False),
        sa.UniqueConstraint("project_id", "scene_id", name="uq_scene_activations_project_scene"),
    )
    op.create_table(
        "datasets",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("org_id", _uuid(), sa.ForeignKey("organizations.id"), nullable=False, index=True),
        sa.Column("project_id", _uuid(), sa.ForeignKey("projects.id"), nullable=True, index=True),
        sa.Column("code", sa.String(128), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("dataset_type", sa.String(32), nullable=False),
        sa.Column("source", sa.String(200), nullable=False, server_default=""),
        sa.Column("format", sa.String(64), nullable=False, server_default=""),
        sa.Column("crs", sa.String(32), nullable=False, server_default="EPSG:4490"),
        sa.Column("bbox_json", _json(), nullable=True),
        sa.Column("time_start", _ts(), nullable=True),
        sa.Column("time_end", _ts(), nullable=True),
        sa.Column("tags", _json(), nullable=False),
        sa.Column("storage_uri", sa.String(1000), nullable=False, server_default=""),
        sa.Column("checksum", sa.String(128), nullable=False, server_default=""),
        sa.Column("metadata_json", _json(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="available"),
        sa.Column("scene_id", _uuid(), sa.ForeignKey("scenes.id"), nullable=True),
        sa.Column("created_at", _ts(), nullable=False),
        sa.Column("updated_at", _ts(), nullable=False),
        sa.Column("deleted_at", _ts(), nullable=True),
        sa.UniqueConstraint("org_id", "code", name="uq_datasets_org_code"),
    )
    op.create_table(
        "baseline_assets",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("org_id", _uuid(), sa.ForeignKey("organizations.id"), nullable=False, index=True),
        sa.Column("project_id", _uuid(), sa.ForeignKey("projects.id"), nullable=True, index=True),
        sa.Column("dataset_id", _uuid(), sa.ForeignKey("datasets.id"), nullable=False),
        sa.Column("code", sa.String(128), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("category", sa.String(64), nullable=False),
        sa.Column("version", sa.String(64), nullable=False),
        sa.Column("valid_from", _ts(), nullable=True),
        sa.Column("valid_to", _ts(), nullable=True),
        sa.Column("applicable_area_json", _json(), nullable=True),
        sa.Column("applicable_area_name", sa.String(200), nullable=False, server_default=""),
        sa.Column("review_status", sa.String(32), nullable=False, server_default="draft"),
        sa.Column("reviewer_id", _uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("reviewed_at", _ts(), nullable=True),
        sa.Column("review_comment", sa.String(2000), nullable=False, server_default=""),
        sa.Column("metadata_json", _json(), nullable=False),
        sa.Column("created_at", _ts(), nullable=False),
        sa.Column("updated_at", _ts(), nullable=False),
        sa.Column("deleted_at", _ts(), nullable=True),
        sa.UniqueConstraint("org_id", "code", "version", name="uq_baselines_org_code_version"),
    )
    op.create_table(
        "tasks",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("org_id", _uuid(), sa.ForeignKey("organizations.id"), nullable=False, index=True),
        sa.Column("project_id", _uuid(), sa.ForeignKey("projects.id"), nullable=False, index=True),
        sa.Column("scene_id", _uuid(), sa.ForeignKey("scenes.id"), nullable=True),
        sa.Column("scene_code", sa.String(64), nullable=False, server_default=""),
        sa.Column("code", sa.String(128), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("task_type", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="queued", index=True),
        sa.Column("priority", sa.String(32), nullable=False, server_default="normal"),
        sa.Column("emergency", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("params_json", _json(), nullable=False),
        sa.Column("progress", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("step", sa.String(64), nullable=False, server_default=""),
        sa.Column("error_message", sa.Text(), nullable=False, server_default=""),
        sa.Column("engine_job_id", sa.String(128), nullable=False, server_default=""),
        sa.Column("result_json", _json(), nullable=False),
        sa.Column("assignee_id", _uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("started_at", _ts(), nullable=True),
        sa.Column("finished_at", _ts(), nullable=True),
        sa.Column("created_at", _ts(), nullable=False),
        sa.Column("updated_at", _ts(), nullable=False),
        sa.Column("deleted_at", _ts(), nullable=True),
        sa.UniqueConstraint("org_id", "code", name="uq_tasks_org_code"),
    )
    op.create_table(
        "products",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("org_id", _uuid(), sa.ForeignKey("organizations.id"), nullable=False, index=True),
        sa.Column("project_id", _uuid(), sa.ForeignKey("projects.id"), nullable=False, index=True),
        sa.Column("scene_id", _uuid(), sa.ForeignKey("scenes.id"), nullable=True),
        sa.Column("scene_code", sa.String(64), nullable=False, server_default=""),
        sa.Column("task_id", _uuid(), sa.ForeignKey("tasks.id"), nullable=True),
        sa.Column("imagery_dataset_id", _uuid(), sa.ForeignKey("datasets.id"), nullable=True),
        sa.Column("baseline_asset_id", _uuid(), sa.ForeignKey("baseline_assets.id"), nullable=True),
        sa.Column("baseline_version", sa.String(64), nullable=False, server_default=""),
        sa.Column("engine_name", sa.String(64), nullable=False, server_default=""),
        sa.Column("engine_params_json", _json(), nullable=False),
        sa.Column("code", sa.String(200), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("product_type", sa.String(64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(32), nullable=False, server_default="draft", index=True),
        sa.Column("storage_uri", sa.String(1000), nullable=False, server_default=""),
        sa.Column("artifacts_json", _json(), nullable=False),
        sa.Column("metadata_json", _json(), nullable=False),
        sa.Column("submitted_at", _ts(), nullable=True),
        sa.Column("reviewed_by", _uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("reviewed_at", _ts(), nullable=True),
        sa.Column("published_at", _ts(), nullable=True),
        sa.Column("withdrawn_at", _ts(), nullable=True),
        sa.Column("withdraw_reason", sa.String(1000), nullable=False, server_default=""),
        sa.Column("review_comment", sa.String(2000), nullable=False, server_default=""),
        sa.Column("created_at", _ts(), nullable=False),
        sa.Column("updated_at", _ts(), nullable=False),
        sa.Column("deleted_at", _ts(), nullable=True),
        sa.UniqueConstraint("org_id", "code", "version", name="uq_products_org_code_version"),
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

    op.create_table(
        "briefings",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("org_id", _uuid(), sa.ForeignKey("organizations.id"), nullable=False, index=True),
        sa.Column("project_id", _uuid(), sa.ForeignKey("projects.id"), nullable=False, index=True),
        sa.Column("scene_id", _uuid(), sa.ForeignKey("scenes.id"), nullable=True),
        sa.Column("scene_code", sa.String(64), nullable=False, server_default=""),
        sa.Column("code", sa.String(128), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
        sa.Column("period_start", _ts(), nullable=True),
        sa.Column("period_end", _ts(), nullable=True),
        sa.Column("content_json", _json(), nullable=False),
        sa.Column("product_ids", _json(), nullable=False),
        sa.Column("published_at", _ts(), nullable=True),
        sa.Column("created_at", _ts(), nullable=False),
        sa.Column("updated_at", _ts(), nullable=False),
        sa.Column("deleted_at", _ts(), nullable=True),
        sa.UniqueConstraint("org_id", "code", name="uq_briefings_org_code"),
    )

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
        sa.Column("asset_type", sa.String(64), nullable=False, index=True),
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
        sa.Column("review_status", sa.String(32), nullable=False, server_default="draft", index=True),
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
        sa.Column("engine_job_id", sa.String(128), nullable=False, server_default="", index=True),
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
    # Columns added to tasks after the GIS-aligned model landed (FKs need later tables).
    op.add_column("tasks", sa.Column("area_id", _uuid(), sa.ForeignKey("areas.id"), nullable=True))
    op.add_column("tasks", sa.Column("progress_json", _json(), nullable=True))
    op.add_column("tasks", sa.Column("error_code", sa.String(64), nullable=False, server_default=""))
    op.add_column("tasks", sa.Column("log_uri", sa.String(1000), nullable=False, server_default=""))
    op.add_column("tasks", sa.Column("idempotency_key", sa.String(200), nullable=True))
    op.add_column("tasks", sa.Column("algo_profile_id", sa.String(128), nullable=False, server_default=""))
    op.add_column("tasks", sa.Column("baseline_version_id", _uuid(), sa.ForeignKey("data_asset_versions.id"), nullable=True))
    op.add_column("tasks", sa.Column("data_ready_at", _ts(), nullable=True))
    op.add_column("tasks", sa.Column("submitted_at", _ts(), nullable=True))
    op.add_column("tasks", sa.Column("processed_at", _ts(), nullable=True))
    op.create_index("ix_tasks_area_id", "tasks", ["area_id"])
    op.create_unique_constraint("uq_tasks_org_idempotency", "tasks", ["org_id", "idempotency_key"])

    op.create_table(
        "audit_logs",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("org_id", _uuid(), sa.ForeignKey("organizations.id"), nullable=True, index=True),
        sa.Column("project_id", _uuid(), nullable=True),
        sa.Column("actor_type", sa.String(32), nullable=False),
        sa.Column("actor_id", _uuid(), nullable=True),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("resource_type", sa.String(64), nullable=False),
        sa.Column("resource_id", sa.String(64), nullable=False),
        sa.Column("request_id", sa.String(64), nullable=False, server_default=""),
        sa.Column("before_json", _json(), nullable=True),
        sa.Column("after_json", _json(), nullable=True),
        sa.Column("created_at", _ts(), nullable=False),
    )


def downgrade() -> None:
    for table in [
        "audit_logs",
        "processing_jobs",
        "impact_stats",
        "product_layers",
        "data_asset_versions",
        "data_assets",
        "briefings",
        "products",
        "tasks",
        "baseline_assets",
        "datasets",
        "algo_profiles",
        "areas",
        "scene_activations",
        "scenes",
        "memberships",
        "service_accounts",
        "projects",
        "users",
        "role_permissions",
        "permissions",
        "roles",
        "organizations",
    ]:
        op.drop_table(table)
