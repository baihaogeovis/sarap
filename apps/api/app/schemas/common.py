from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class LoginIn(BaseModel):
    email: str
    password: str


class RefreshIn(BaseModel):
    refresh_token: str


class TokenOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class UserOut(ORMModel):
    id: uuid.UUID
    email: str
    name: str
    status: str
    roles: list[str] = []
    permissions: list[str] = []
    org_id: uuid.UUID | None = None


class ProjectIn(BaseModel):
    code: str
    name: str
    default_crs: str = "EPSG:4548"
    bbox_json: dict[str, Any] | None = None
    aoi_wkt: str | None = None
    # Ignored if present — tenancy comes from the auth context.
    org_id: uuid.UUID | None = Field(default=None, description="Ignored; org_id is taken from auth.")


class ProjectOut(ORMModel):
    id: uuid.UUID
    org_id: uuid.UUID
    code: str
    name: str
    status: str
    default_crs: str
    bbox_json: dict[str, Any] | None
    aoi_wkt: str | None
    created_at: datetime


class MemberIn(BaseModel):
    user_id: uuid.UUID
    role_code: str
    org_id: uuid.UUID | None = None


class MemberOut(ORMModel):
    id: uuid.UUID
    user_id: uuid.UUID
    org_id: uuid.UUID
    scope_type: str
    scope_id: uuid.UUID
    role_code: str


class SceneOut(ORMModel):
    id: uuid.UUID
    code: str
    name: str
    description: str
    version: str
    status: str
    manifest_json: dict[str, Any]


class SceneActivateIn(BaseModel):
    scene_code: str
    config_json: dict[str, Any] = Field(default_factory=dict)
    org_id: uuid.UUID | None = None


class SceneActivationOut(ORMModel):
    id: uuid.UUID
    org_id: uuid.UUID
    project_id: uuid.UUID
    scene_id: uuid.UUID
    status: str
    config_json: dict[str, Any]


class DatasetIn(BaseModel):
    code: str
    name: str
    dataset_type: str
    project_id: uuid.UUID | None = None
    source: str = ""
    format: str = ""
    crs: str = "EPSG:4490"
    bbox_json: dict[str, Any] | None = None
    time_start: datetime | None = None
    time_end: datetime | None = None
    s1_product_id: str = ""
    storage_uri: str = ""
    metadata_json: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)
    org_id: uuid.UUID | None = None


class DatasetOut(ORMModel):
    id: uuid.UUID
    org_id: uuid.UUID
    project_id: uuid.UUID | None
    code: str
    name: str
    dataset_type: str
    source: str
    format: str
    crs: str
    bbox_json: dict[str, Any] | None
    time_start: datetime | None = None
    time_end: datetime | None = None
    s1_product_id: str = ""
    storage_uri: str
    metadata_json: dict[str, Any]
    status: str


class BaselineIn(BaseModel):
    code: str
    name: str
    category: str
    version: str
    dataset_id: uuid.UUID
    project_id: uuid.UUID | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    applicable_area_json: dict[str, Any] | None = None
    applicable_area_name: str = ""
    metadata_json: dict[str, Any] = Field(default_factory=dict)
    org_id: uuid.UUID | None = None


class BaselineOut(ORMModel):
    id: uuid.UUID
    org_id: uuid.UUID
    project_id: uuid.UUID | None
    dataset_id: uuid.UUID
    code: str
    name: str
    category: str
    version: str
    valid_from: datetime | None
    valid_to: datetime | None
    review_status: str
    applicable_area_name: str
    metadata_json: dict[str, Any]


class BaselineReviewIn(BaseModel):
    review_status: str
    comment: str = ""


class TaskIn(BaseModel):
    project_id: uuid.UUID
    scene_code: str
    task_type: str
    title: str
    params_json: dict[str, Any] = Field(default_factory=dict)
    emergency: bool = False
    imagery_dataset_id: uuid.UUID | None = None
    baseline_asset_id: uuid.UUID | None = None
    baseline_version_id: uuid.UUID | None = None
    area_id: uuid.UUID | None = None
    idempotency_key: str | None = None
    force_rerun: bool = False
    data_ready_at: datetime | None = None
    algo_profile_id: str = ""
    acquisition_start: datetime | None = None
    acquisition_end: datetime | None = None
    s1_product_id: str = ""
    org_id: uuid.UUID | None = None


class TaskOut(ORMModel):
    id: uuid.UUID
    org_id: uuid.UUID
    project_id: uuid.UUID
    area_id: uuid.UUID | None = None
    scene_id: uuid.UUID | None
    scene_code: str
    code: str
    title: str
    task_type: str
    status: str
    priority: str
    emergency: bool
    params_json: dict[str, Any]
    progress: int
    progress_json: dict[str, Any] = Field(default_factory=dict)
    step: str
    error_message: str
    error_code: str = ""
    log_uri: str = ""
    engine_job_id: str
    result_json: dict[str, Any]
    idempotency_key: str | None = None
    algo_profile_id: str = ""
    baseline_version_id: uuid.UUID | None = None
    data_ready_at: datetime | None = None
    submitted_at: datetime | None = None
    processed_at: datetime | None = None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
    acquisition_start: datetime | None = None
    acquisition_end: datetime | None = None
    s1_product_id: str = ""


class ProductIn(BaseModel):
    project_id: uuid.UUID
    scene_code: str = ""
    product_type: str
    title: str
    code: str | None = None
    task_id: uuid.UUID | None = None
    area_id: uuid.UUID | None = None
    imagery_dataset_id: uuid.UUID | None = None
    baseline_asset_id: uuid.UUID | None = None
    data_asset_id: uuid.UUID | None = None
    baseline_version: str = ""
    baseline_version_id: uuid.UUID | None = None
    engine_name: str = ""
    engine_params_json: dict[str, Any] = Field(default_factory=dict)
    storage_uri: str = ""
    artifacts_json: list[Any] = Field(default_factory=list)
    metadata_json: dict[str, Any] = Field(default_factory=dict)
    extracted_water_ha: float | None = None
    water_current_ha: float | None = None
    flood_event_ha: float | None = None
    lowconf_ha: float | None = None
    flood_event_status: str | None = None
    data_ready_at: datetime | None = None
    processed_at: datetime | None = None
    suggested_target_minutes: int = 240
    acquisition_start: datetime | None = None
    acquisition_end: datetime | None = None
    s1_product_id: str = ""
    org_id: uuid.UUID | None = None


class ProductOut(ORMModel):
    id: uuid.UUID
    org_id: uuid.UUID
    project_id: uuid.UUID
    area_id: uuid.UUID | None = None
    scene_code: str
    task_id: uuid.UUID | None
    imagery_dataset_id: uuid.UUID | None
    baseline_asset_id: uuid.UUID | None
    data_asset_id: uuid.UUID | None = None
    baseline_version: str
    baseline_version_id: uuid.UUID | None = None
    engine_name: str
    engine_params_json: dict[str, Any]
    code: str
    title: str
    product_type: str
    version: int
    status: str
    storage_uri: str
    artifacts_json: list[Any]
    metadata_json: dict[str, Any]
    flood_event_status: str = "none"
    extracted_water_ha: float | None = None
    water_current_ha: float | None = None
    flood_event_ha: float | None = None
    lowconf_ha: float | None = None
    suggested_target_minutes: int = 240
    data_ready_at: datetime | None = None
    submitted_at: datetime | None = None
    processed_at: datetime | None = None
    review_comment: str
    reject_reason: str = ""
    withdraw_reason: str
    re_qc_required: bool = False
    supersedes_id: uuid.UUID | None = None
    published_at: datetime | None
    withdrawn_at: datetime | None
    created_at: datetime
    acquisition_start: datetime | None = None
    acquisition_end: datetime | None = None
    s1_product_id: str = ""


class TransitionIn(BaseModel):
    comment: str = ""
    reason: str = ""


class BriefingIn(BaseModel):
    project_id: uuid.UUID
    title: str
    scene_code: str = ""
    content_json: dict[str, Any] = Field(default_factory=dict)
    product_ids: list[uuid.UUID] = Field(default_factory=list)
    org_id: uuid.UUID | None = None


class BriefingOut(ORMModel):
    id: uuid.UUID
    org_id: uuid.UUID
    project_id: uuid.UUID
    scene_code: str
    code: str
    title: str
    status: str
    content_json: dict[str, Any]
    product_ids: list[Any]
    published_at: datetime | None
    created_at: datetime


class InternalProductIn(BaseModel):
    task_id: uuid.UUID
    product_type: str
    title: str
    code: str | None = None
    storage_uri: str = ""
    artifacts_json: list[Any] = Field(default_factory=list)
    metadata_json: dict[str, Any] = Field(default_factory=dict)
    engine_name: str = ""
    engine_params_json: dict[str, Any] = Field(default_factory=dict)
    baseline_version: str = ""
    baseline_version_id: uuid.UUID | None = None
    data_asset_id: uuid.UUID | None = None
    imagery_dataset_id: uuid.UUID | None = None
    baseline_asset_id: uuid.UUID | None = None
    extracted_water_ha: float | None = None
    water_current_ha: float | None = None
    flood_event_ha: float | None = None
    lowconf_ha: float | None = None
    flood_event_status: str | None = None
    processed_at: datetime | None = None
    acquisition_start: datetime | None = None
    acquisition_end: datetime | None = None
    s1_product_id: str = ""
    qc_warnings: list[str] = Field(default_factory=list)
    error_code: str = ""

class AreaIn(BaseModel):
    code: str
    name: str
    is_pilot: bool = False
    timezone: str = "Asia/Shanghai"
    aoi_geojson: dict[str, Any] | None = None
    bbox_json: dict[str, Any] | None = None
    analysis_crs: str | None = None
    exchange_crs: str = "EPSG:4490"
    grid_res_m: int = 10
    grid_origin_x: float = 0
    grid_origin_y: float = 0
    config_json: dict[str, Any] = Field(default_factory=dict)
    org_id: uuid.UUID | None = None

class AreaOut(ORMModel):
    id: uuid.UUID
    org_id: uuid.UUID
    project_id: uuid.UUID
    code: str
    name: str
    status: str
    is_pilot: bool
    timezone: str
    aoi_geojson: dict[str, Any] | None
    bbox_json: dict[str, Any] | None
    analysis_crs: str
    exchange_crs: str
    grid_res_m: int
    grid_origin_x: float
    grid_origin_y: float
    config_json: dict[str, Any]
    created_at: datetime

class DataAssetIn(BaseModel):
    asset_code: str
    name: str
    asset_type: str
    description: str = ""
    owner: str = ""
    default_crs: str = "EPSG:4490"
    project_id: uuid.UUID | None = None
    area_id: uuid.UUID | None = None
    org_id: uuid.UUID | None = None

class DataAssetOut(ORMModel):
    id: uuid.UUID
    org_id: uuid.UUID
    project_id: uuid.UUID | None
    area_id: uuid.UUID | None
    asset_code: str
    name: str
    asset_type: str
    description: str
    owner: str
    default_crs: str
    status: str
    created_at: datetime

class DataAssetVersionIn(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    version_no: str
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    applicable_area_geojson: dict[str, Any] | None = None
    applicable_area_name: str = ""
    source: str = ""
    algorithm_profile_id: str = ""
    spatial_res_m: float | None = None
    crs: str = "EPSG:4490"
    gsd_note: str = ""
    checksum: str = ""
    byte_size: int = 0
    storage_uri: str = ""
    preview_uri: str = ""
    schema_json: dict[str, Any] = Field(default_factory=dict)
    lineage_json: dict[str, Any] = Field(default_factory=dict)

class DataAssetVersionOut(ORMModel):
    model_config = ConfigDict(from_attributes=True, protected_namespaces=())

    id: uuid.UUID
    org_id: uuid.UUID
    asset_id: uuid.UUID
    version_no: str
    valid_from: datetime | None
    valid_to: datetime | None
    applicable_area_geojson: dict[str, Any] | None
    applicable_area_name: str
    review_status: str
    reviewer_id: uuid.UUID | None
    reviewed_at: datetime | None
    review_comment: str
    source: str
    algorithm_profile_id: str
    spatial_res_m: float | None
    crs: str
    storage_uri: str
    checksum: str
    byte_size: int
    created_at: datetime

class ReviewIn(BaseModel):
    comment: str = ""
    reason: str = ""

class ServiceAccountIn(BaseModel):
    name: str
    client_id: str | None = None
    scopes: list[str] = Field(default_factory=lambda: ["api.invoke"])
    project_id: uuid.UUID | None = None
    org_id: uuid.UUID | None = None

class ServiceAccountOut(ORMModel):
    id: uuid.UUID
    org_id: uuid.UUID
    project_id: uuid.UUID | None
    client_id: str
    name: str
    scopes: list[Any]
    status: str
    key_prefix: str
    revoked_at: datetime | None
    created_at: datetime
    api_key: str | None = None

class ProductLayerOut(ORMModel):
    id: uuid.UUID
    product_id: uuid.UUID
    layer_key: str
    media_type: str
    storage_uri: str
    metadata_json: dict[str, Any]

class ImpactStatOut(ORMModel):
    id: uuid.UUID
    product_id: uuid.UUID
    object_type: str
    object_id: str
    object_name: str
    metric: str
    value: float
    unit: str
    scope: str
    extra_json: dict[str, Any]
