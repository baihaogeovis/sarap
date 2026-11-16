"""默认算法档 s1_grd_flood_v1，参数可被试点 overrides 覆盖。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from sarap_engine.constants import (
    DEFAULT_ALGO_PROFILE_ID,
    DEFAULT_AOI_BUFFER_KM,
    DEFAULT_INCIDENCE_DEG,
    DEFAULT_MMU_HA,
    DEFAULT_MORPH_KERNEL_PX,
    DEFAULT_PIXEL_SPACING_M,
    DEFAULT_SLOPE_DEG,
    DEFAULT_T_CLAMP,
    DEFAULT_T_DEFAULT,
    DEFAULT_T_VH_BRIGHT,
    UrbanPolicy,
)

_PACKAGED_DEFAULTS = Path(__file__).resolve().parent / "data" / "s1_grd_flood_v1.defaults.json"
# 规范原文路径（只作对照，运行时优先用包内副本）
_SPEC_DEFAULTS = Path("/workspace/SARAP/specs/s1_grd_flood_v1.defaults.json")
_SPEC_GRAPH = Path("/workspace/SARAP/specs/s1_grd_flood_v1.xml.j2")


class SnapParams(BaseModel):
    graph_template: str = "s1_grd_flood_v1.xml.j2"
    preferred_snap_version: str = "10.x"
    pixel_spacing_m: float = DEFAULT_PIXEL_SPACING_M
    filter: str = "Refined Lee"
    filter_window: str = "7x7"
    dem_name: str = "Copernicus 30m Global DEM"
    orbit_type: str = "Sentinel Precise (Auto Download)"
    continue_on_orbit_fail: bool = True
    border_noise_if_ipf_lt: str = "3.10"
    force_border_noise_removal: bool = False
    mask_sea_nodata: bool = False
    poly_degree: int = 3


class ExtractParams(BaseModel):
    T_default_vv_db: float = DEFAULT_T_DEFAULT
    T_clamp_vv_db: tuple[float, float] = DEFAULT_T_CLAMP
    incidence_deg: tuple[float, float] = DEFAULT_INCIDENCE_DEG
    slope_deg: float = DEFAULT_SLOPE_DEG
    mmu_ha: float = DEFAULT_MMU_HA
    morph_kernel_px: int = DEFAULT_MORPH_KERNEL_PX
    use_vh_constraint: bool = True
    T_VH_bright_db: float = DEFAULT_T_VH_BRIGHT
    urban_policy: UrbanPolicy = UrbanPolicy.DOWNGRADE
    use_preevent: bool = False
    preevent_window_days: tuple[int, int] = (2, 24)
    delta_db_mode_b: float = 3.0
    aoi_buffer_km: float = DEFAULT_AOI_BUFFER_KM
    keep_adjacent_small_patches: bool = False
    min_valid_coverage_ratio: float | None = None


class AlgoProfile(BaseModel):
    algo_profile_id: str = DEFAULT_ALGO_PROFILE_ID
    spec_id: str = "SARAP-SPEC-FLOOD-V1"
    spec_version: str = "1.1.0"
    snap: SnapParams = Field(default_factory=SnapParams)
    extract: ExtractParams = Field(default_factory=ExtractParams)

    def apply_overrides(self, overrides: dict[str, Any] | None) -> "AlgoProfile":
        if not overrides:
            return self.model_copy(deep=True)
        extract_data = self.extract.model_dump()
        snap_data = self.snap.model_dump()
        alias = {
            "T_default": "T_default_vv_db",
            "T_clamp": "T_clamp_vv_db",
            "incidence_deg": "incidence_deg",
            "slope_deg": "slope_deg",
            "mmu_ha": "mmu_ha",
            "urban_policy": "urban_policy",
            "use_vh_constraint": "use_vh_constraint",
            "use_preevent": "use_preevent",
            "mask_sea_nodata": "mask_sea_nodata",
            "buffer_km": "aoi_buffer_km",
            "force_border_noise_removal": "force_border_noise_removal",
            "keep_adjacent_small_patches": "keep_adjacent_small_patches",
            "T_VH_bright": "T_VH_bright_db",
            "morph_kernel_px": "morph_kernel_px",
        }
        for raw_key, value in overrides.items():
            key = alias.get(raw_key, raw_key)
            if key in extract_data:
                extract_data[key] = value
            elif key in snap_data:
                snap_data[key] = value
        return self.model_copy(
            update={
                "extract": ExtractParams.model_validate(extract_data),
                "snap": SnapParams.model_validate(snap_data),
            }
        )

    def param_hash(self) -> str:
        payload = self.model_dump(mode="json")
        blob = json.dumps(payload, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_default_profile() -> AlgoProfile:
    data: dict[str, Any] = {}
    if _PACKAGED_DEFAULTS.is_file():
        data = _load_json(_PACKAGED_DEFAULTS)
    elif _SPEC_DEFAULTS.is_file():
        data = _load_json(_SPEC_DEFAULTS)
    snap_in = data.get("snap") or {}
    extract_in = data.get("extract") or {}
    snap = SnapParams(
        graph_template=str(snap_in.get("graph_template") or "s1_grd_flood_v1.xml.j2"),
        preferred_snap_version=str(snap_in.get("preferred_snap_version") or "10.x"),
        pixel_spacing_m=float(snap_in.get("pixel_spacing_m") or DEFAULT_PIXEL_SPACING_M),
        filter=str(snap_in.get("filter") or "Refined Lee"),
        filter_window=str(snap_in.get("filter_window") or "7x7"),
        dem_name=str(snap_in.get("dem_name") or "Copernicus 30m Global DEM"),
        orbit_type=str(snap_in.get("orbit_type") or "Sentinel Precise (Auto Download)"),
        continue_on_orbit_fail=bool(snap_in.get("continue_on_orbit_fail", True)),
        border_noise_if_ipf_lt=str(snap_in.get("border_noise_if_ipf_lt") or "3.10"),
    )
    extract = ExtractParams(
        T_default_vv_db=float(extract_in.get("T_default_vv_db", DEFAULT_T_DEFAULT)),
        T_clamp_vv_db=tuple(extract_in.get("T_clamp_vv_db") or DEFAULT_T_CLAMP),  # type: ignore[arg-type]
        incidence_deg=tuple(extract_in.get("incidence_deg") or DEFAULT_INCIDENCE_DEG),  # type: ignore[arg-type]
        slope_deg=float(extract_in.get("slope_deg", DEFAULT_SLOPE_DEG)),
        mmu_ha=float(extract_in.get("mmu_ha", DEFAULT_MMU_HA)),
        morph_kernel_px=int(extract_in.get("morph_kernel_px", DEFAULT_MORPH_KERNEL_PX)),
        use_vh_constraint=bool(extract_in.get("use_vh_constraint", True)),
        T_VH_bright_db=float(extract_in.get("T_VH_bright_db", DEFAULT_T_VH_BRIGHT)),
        urban_policy=UrbanPolicy(extract_in.get("urban_policy") or UrbanPolicy.DOWNGRADE),
        use_preevent=bool(extract_in.get("use_preevent", False)),
        preevent_window_days=tuple(extract_in.get("preevent_window_days") or (2, 24)),  # type: ignore[arg-type]
        delta_db_mode_b=float(extract_in.get("delta_db_mode_b", 3.0)),
        aoi_buffer_km=float(extract_in.get("aoi_buffer_km", DEFAULT_AOI_BUFFER_KM)),
    )
    return AlgoProfile(
        algo_profile_id=str(data.get("algo_profile_id") or DEFAULT_ALGO_PROFILE_ID),
        spec_id=str(data.get("spec_id") or "SARAP-SPEC-FLOOD-V1"),
        spec_version=str(data.get("spec_version") or "1.1.0"),
        snap=snap,
        extract=extract,
    )


def packaged_graph_template_path() -> Path:
    return (
        Path(__file__).resolve().parents[1]
        / "plugins"
        / "snap"
        / "graphs"
        / "s1_grd_flood_v1.xml.j2"
    )


def official_graph_template_path() -> Path:
    if _SPEC_GRAPH.is_file():
        return _SPEC_GRAPH
    return packaged_graph_template_path()
