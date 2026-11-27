"""产品 / 图层 / 元数据模型，对齐规范第 9 节与 v1.1.0 第 0 节。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from sarap_engine.constants import LIMITATIONS


class ProductLayer(BaseModel):
    name: str
    uri: str
    media_type: str = "application/octet-stream"
    role: str | None = None
    empty: bool = False
    note: str | None = None
    # Ingest-only payload (display pixels, GeoPDF bytes). Kept off the job JSON.
    extra: dict[str, Any] = Field(default_factory=dict, exclude=True)


class ProductMetadata(BaseModel):
    product_id: str
    product_type: str = "SARAP_FLOOD_V1"
    product_version: str = "1.1.0"
    spec_version: str = "1.1.0"
    area_id: str | None = None
    is_pilot: bool = False
    pilot_id: str | None = None
    scene_id: str = ""
    scene_code: str | None = None
    s1_product_id: str | None = None
    platform: str = "S1A"
    mode: str = "IW"
    product_level: str = "GRD"
    polarizations: list[str] = Field(default_factory=lambda: ["VV", "VH"])
    pass_direction: str = "ASCENDING"
    ipf_version: str = ""
    orbit_type: str = "precise"
    acquisition_start: datetime | None = None
    acquisition_end: datetime | None = None
    processed_at: datetime | None = None
    published_at: datetime | None = None
    sla_minutes: int = 240  # 内部别名，对外请用 suggested_target_minutes
    suggested_target_minutes: int = 240
    external_target_hours: int = 4
    contract_commitment: bool = False
    data_ready_at: datetime | None = None
    submitted_at: datetime | None = None
    crs: str = "EPSG:4548"
    resolution_m: float = 10.0
    grid_origin: list[float] = Field(default_factory=lambda: [0.0, 0.0])
    aoi_coverage_ratio: float | None = None
    algo_profile_id: str = "s1_grd_flood_v1"
    snap_version: str | None = None
    threshold_vv_db: float | None = None
    threshold_vv_source: str | None = None
    threshold_default_db: float | None = None
    mmu_ha: float = 0.3
    baseline_asset_id: str | None = None
    baseline_version_id: str | None = None
    baseline_type: str | None = None
    preevent_scene_id: str | None = None
    urban_policy: str = "downgrade"
    flood_event_status: str = "none"
    extracted_water_ha: float | None = None
    extracted_water_area_label: str | None = None
    water_current_ha: float | None = None
    flood_event_ha: float | None = None
    lowconf_ha: float | None = None
    review_status: str = "draft"
    limitations: list[str] = Field(default_factory=lambda: list(LIMITATIONS))
    param_hash: str | None = None
    extras: dict[str, Any] = Field(default_factory=dict)

    def to_public_dict(self) -> dict[str, Any]:
        data = self.model_dump(mode="json")
        # 统一时间字段为 Z
        for key in (
            "acquisition_start",
            "acquisition_end",
            "processed_at",
            "published_at",
            "data_ready_at",
            "submitted_at",
        ):
            val = data.get(key)
            if isinstance(val, str) and val.endswith("+00:00"):
                data[key] = val[:-6] + "Z"
        # 对外时效用建议目标，不把 sla 写成合同承诺
        data["suggested_target_minutes"] = int(
            data.get("suggested_target_minutes") or data.get("sla_minutes") or 240
        )
        data["contract_commitment"] = False
        data.pop("sla_minutes", None)
        depth_frags = ("depth", "water_depth", "flood_depth")

        def drop_depth(obj):
            if isinstance(obj, dict):
                return {
                    key: drop_depth(value)
                    for key, value in obj.items()
                    if not any(frag in str(key).lower() for frag in depth_frags)
                }
            if isinstance(obj, list):
                return [drop_depth(item) for item in obj]
            return obj

        return drop_depth(data)


class ProductManifest(BaseModel):
    product_id: str
    layers: list[ProductLayer] = Field(default_factory=list)
    metadata: ProductMetadata | None = None
    qc_summary: dict[str, Any] = Field(default_factory=dict)
    impact_stats: dict[str, Any] = Field(default_factory=dict)
    work_dir: str | None = None
