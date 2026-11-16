"""景元数据。下载由平台负责，引擎假设输入路径已就绪。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class SceneMeta(BaseModel):
    scene_id: str = ""  # 平台场景（如 flood），不是 S1 PRODUCT-ID
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

    @property
    def has_vv(self) -> bool:
        return any(p.upper() == "VV" for p in self.polarizations)

    @property
    def has_vh(self) -> bool:
        return any(p.upper() == "VH" for p in self.polarizations)

    @property
    def product_label(self) -> str:
        """用于产品命名的成像标识：优先 S1 PRODUCT-ID。"""
        return self.s1_product_id or self.scene_id or self.scene_code or "SCENE"

