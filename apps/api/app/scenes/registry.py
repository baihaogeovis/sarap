"""Registered scene manifests. Flood is a catalog entry, not the only app."""

from __future__ import annotations

from typing import Any

# Official flood defaults from docs/specs/s1_grd_flood_v1.defaults.json
# and SARAP-v1-flood-product-spec.md. Do not invent a depth product or CRS.
FLOOD_MANIFEST: dict[str, Any] = {
    "code": "flood",
    "name": "洪水应急",
    "version": "1.0.0",
    "spec_id": "SARAP-SPEC-FLOOD-V1",
    "algo_profile_id": "s1_grd_flood_v1",
    "task_types": ["water_extract", "change_detect", "flood_pipeline"],
    "product_types": ["SARAP_FLOOD_V1"],
    "product_layers": [
        "class_map",
        "flood_event",
        "water_current",
        "qc_flags",
        "flood_event_poly",
        "water_current_poly",
        "thematic_map",
        "impact_stats",
        "metadata",
    ],
    "class_codes": {
        "0": "nodata",
        "1": "non_water",
        "2": "permanent_or_baseline_water",
        "3": "flood_event",
        "4": "water_lowconf",
        "5": "extracted_water",
    },
    "p0_layers": ["class_map", "water_current", "water_current_poly", "qc_flags", "qc_summary", "metadata"],
    "p1_layers_with_baseline": ["flood_event", "flood_event_poly"],
    "recommended_baselines": [
        "permanent_water",
        "seasonal_water",
        "ref_admin_county",
        "ref_admin_township",
        "ref_road",
        "ref_settlement",
        "ref_dem",
    ],
    "extended_baselines": ["ref_cropland"],
    "impact_objects": ["admin_county", "admin_township", "road", "settlement"],
    "extended_impact_objects": ["cropland"],
    "briefing_template": "flood_emergency_v1",
    "not_in_v1": ["water_depth", "hourly_revisit_claim", "indoor_or_under_canopy_complete_detection"],
    "suggested_target_minutes": 240,
    "grid": {"res_m": 10},
}

# Demo seed only — replace the AOI when a real pilot is chosen. Not a named basin.
DEMO_PILOT_CONFIG: dict[str, Any] = {
    "pilot_id": "demo-pilot",
    "name": "示例试点（请按实际试点区替换）",
    "timezone": "Asia/Shanghai",
    "aoi": {"crs": "EPSG:4490", "minx": 116.2, "miny": 39.6, "maxx": 116.8, "maxy": 40.1},
    "analysis_crs": "EPSG:4548",
    "grid": {"res_m": 10, "origin_x": 0, "origin_y": 0},
    "s1": {"modes": ["IW"], "product_level": "GRD", "polarizations": ["VV", "VH"]},
    "algo_profile_id": "s1_grd_flood_v1",
    "overrides": {
        "T_default": -18,
        "T_clamp": [-23, -14],
        "mmu_ha": 0.3,
        "slope_deg": 15,
        "incidence_deg": [30, 45],
        "urban_policy": "downgrade",
        "use_vh_constraint": True,
        "use_preevent": False,
        "buffer_km": 2,
    },
    "suggested_target_minutes": 240,
    # Compact public-validation window shipped with the engine. Not a domestic AOI.
    "impact_assets": {
        "admin_county": "fixture:public_validation_window",
        "admin_township": "fixture:public_validation_window",
        "road": "fixture:public_validation_window",
        "settlement": "fixture:public_validation_window",
    },
}

_REGISTRY = {"flood": FLOOD_MANIFEST}


def get_manifest(code: str) -> dict[str, Any] | None:
    return _REGISTRY.get(code)
