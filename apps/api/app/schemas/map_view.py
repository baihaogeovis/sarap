"""OpenAPI models for the one-map payload. Runtime responses stay envelopes built by hand."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class MapRasterOut(BaseModel):
    layer_key: str
    title: str
    kind: str
    tile_template: str
    cog_path: str
    bounds: list[float]


class MapVectorOut(BaseModel):
    layer_key: str
    title: str
    kind: str
    fill: bool = True
    geojson: dict[str, Any]


class MapProductOut(BaseModel):
    id: str
    title: str
    status: str
    flood_event_status: str
    baseline_version: str = ""
    baseline_version_id: str | None = None
    version: int
    scene_code: str
    extracted_water_ha: float | None = None
    water_current_ha: float | None = None
    flood_event_ha: float | None = None
    acquisition_start: str | None = None
    s1_product_id: str | None = None
    layers: list[MapVectorOut]
    rasters: list[MapRasterOut] = Field(default_factory=list)
    geopdf_path: str | None = None
    impact: dict[str, Any] = Field(default_factory=dict)
    impact_including_lowconf: dict[str, Any] = Field(default_factory=dict)
    emergency_map: dict[str, Any] | None = None


class MapAreaOut(BaseModel):
    id: str
    name: str
    analysis_crs: str
    exchange_crs: str
    aoi: dict[str, Any] | None = None


class MapPayloadOut(BaseModel):
    area: MapAreaOut
    products: list[MapProductOut]


class MapEnvelope(BaseModel):
    data: MapPayloadOut
    error: dict[str, Any] | None = None
    meta: dict[str, Any] = Field(default_factory=dict)
