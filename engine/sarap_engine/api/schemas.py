"""Pydantic v2 请求 / 响应。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class SceneInput(BaseModel):
    scene_id: str | None = None  # 平台场景（如 flood），不是 S1 PRODUCT-ID
    s1_product_id: str | None = None
    scene_code: str | None = None
    platform: str = "S1A"
    mode: str = "IW"
    product_level: str = "GRD"
    polarizations: list[str] = Field(default_factory=lambda: ["VV", "VH"])
    pass_direction: str = "ASCENDING"
    ipf_version: str = "3.80"
    absolute_orbit: int | None = None
    orbit_type: str = "precise"
    acquisition_start: datetime | None = None
    acquisition_end: datetime | None = None
    footprint_wkt: str | None = None
    input_uri: str | None = None
    checksum: str | None = None
    data_ready_at: datetime | None = None


class GridInput(BaseModel):
    res_m: float = 10.0
    origin_x: float = 0.0
    origin_y: float = 0.0
    width: int | None = 80
    height: int | None = 80


class PilotInput(BaseModel):
    area_id: str | None = None
    pilot_id: str | None = None  # 兼容旧字段，不再作为必填或空间主键
    is_pilot: bool = False
    name: str = ""
    timezone: str = "Asia/Shanghai"
    analysis_crs: str = "EPSG:4548"
    exchange_crs: str = "EPSG:4490"
    aoi_wkt: str | None = None
    aoi_crs: str = "EPSG:4490"
    grid: GridInput = Field(default_factory=GridInput)
    algo_profile_id: str = "s1_grd_flood_v1"
    overrides: dict[str, Any] = Field(default_factory=dict)
    sla_minutes: int = 240
    suggested_target_minutes: int = 240
    impact_assets: dict[str, Any] = Field(default_factory=dict)


class JobSubmitRequest(BaseModel):
    task_id: str | None = None
    org_id: str | None = None
    project_id: str | None = None
    scene_code: str | None = None
    task_type: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    scene_id: str | None = None  # 平台场景 UUID，不是 Sentinel-1 PRODUCT-ID
    area_id: str | None = None
    is_pilot: bool | None = None
    s1_product_id: str | None = None
    acquisition_start: datetime | None = None
    acquisition_end: datetime | None = None
    pilot_id: str | None = None  # 兼容旧调用，提交时不要作为必填
    scene: SceneInput | None = None
    pilot: PilotInput | None = None
    baseline_version_id: str | None = None
    baseline_uri: str | None = None
    baseline_asset_id: str | None = None
    baseline_type: str | None = None
    algo_profile_id: str = "s1_grd_flood_v1"
    execution_mode: Literal["mock", "snap", "pie_sar"] | None = None
    force_rerun: bool = False
    priority: Literal["normal", "emergency"] = "normal"
    param_overrides: dict[str, Any] = Field(default_factory=dict)
    data_ready_at: datetime | None = None
    use_synthetic_baseline: bool | None = None
    extras: dict[str, Any] = Field(default_factory=dict)


class PriorityRequest(BaseModel):
    priority: Literal["emergency", "normal"] = "emergency"


class HealthResponse(BaseModel):
    status: str
    mode: str
    gpt_available: bool
    version: str
    spec_version: str
