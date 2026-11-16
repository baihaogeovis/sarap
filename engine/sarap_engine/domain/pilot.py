"""试点 / 区域配置模型，对应规范第 12 节；不写死流域。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, model_validator


class GridConfig(BaseModel):
    res_m: float = 10.0
    origin_x: float = 0.0
    origin_y: float = 0.0
    width: int | None = None
    height: int | None = None
    transform: tuple[float, float, float, float, float, float] | None = None
    """GDAL 风格仿射：(origin_x, res_x, 0, origin_y, 0, -res_y)。"""

    def affine(self) -> tuple[float, float, float, float, float, float]:
        if self.transform is not None:
            return self.transform
        return (self.origin_x, self.res_m, 0.0, self.origin_y, 0.0, -self.res_m)


class ImpactAssets(BaseModel):
    admin_county: str | None = None
    admin_township: str | None = None
    road: str | None = None
    settlement: str | None = None
    cropland: str | None = None  # 扩展，非 P1 必选

    def configured_types(self) -> list[str]:
        mapping = {
            "admin_county": self.admin_county,
            "admin_township": self.admin_township,
            "road": self.road,
            "settlement": self.settlement,
            "cropland": self.cropland,
        }
        return [k for k, v in mapping.items() if v]


class BaselineRefs(BaseModel):
    permanent_water_asset_id: str | None = None
    seasonal_water_asset_id: str | None = None
    preferred_version_id: str | None = None


class PilotConfig(BaseModel):
    area_id: str | None = None
    pilot_id: str | None = None  # 兼容旧字段；区域主键是 area_id
    is_pilot: bool = False
    name: str = ""
    timezone: str = "Asia/Shanghai"
    analysis_crs: str = "EPSG:4548"
    exchange_crs: str = "EPSG:4490"
    aoi_wkt: str | None = None
    aoi_crs: str = "EPSG:4490"
    grid: GridConfig = Field(default_factory=GridConfig)
    algo_profile_id: str = "s1_grd_flood_v1"
    overrides: dict[str, Any] = Field(default_factory=dict)
    baselines: BaselineRefs = Field(default_factory=BaselineRefs)
    impact_assets: ImpactAssets = Field(default_factory=ImpactAssets)
    sla_minutes: int = 240  # 兼容旧字段；对外用 suggested_target_minutes
    suggested_target_minutes: int = 240  # 默认 4 小时，非合同承诺
    mask_sea_nodata: bool = False

    @model_validator(mode="after")
    def _require_area(self) -> "PilotConfig":
        if not self.area_id and self.pilot_id:
            self.area_id = self.pilot_id
        if not self.area_id:
            raise ValueError("area_id 必填（区域是主对象；pilot_id 不是必填项）")
        return self

    @property
    def region_id(self) -> str:
        return self.area_id or self.pilot_id or ""

    @classmethod
    def example(cls, area_id: str = "area_demo", *, is_pilot: bool = False) -> "PilotConfig":
        return cls(area_id=area_id, is_pilot=is_pilot, name="示例区域")
