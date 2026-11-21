"""共享后处理工作流：extract / change / qc / vectorize / impact / package。

算法在 sarap_engine.algo，此处负责把预处理结果装配成产品。
mock 与 snap 共用此通路。
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from sarap_engine.algo.area import area_stats
from sarap_engine.algo.change import classify_with_baseline, classify_without_baseline
from sarap_engine.algo.extract import extract_water
from sarap_engine.algo.grid import GridMisaligned, GridSpec, assert_grids_aligned
from sarap_engine.algo.impact import build_emergency_map, load_impact_objects, overlay_impacts
from sarap_engine.algo.qc import apply_risk_downgrade, flag_area_ha
from sarap_engine.constants import (
    AREA_LIMITATION,
    EXTERNAL_TARGET_HOURS,
    EXTRACTED_WATER_AREA_LABEL,
    INTERNAL_BUDGET_MINUTES,
    LIMITATIONS,
    NO_IMPACT_ASSETS_NOTE,
    EngineError,
    ErrorCode,
    QcFlag,
)
from sarap_engine.domain.algo_profile import AlgoProfile
from sarap_engine.plugins.base import PluginContext, PreprocessResult
from sarap_engine.products.exporters import package_product
from sarap_engine.products.models import ProductManifest, ProductMetadata
from sarap_engine.products.naming import product_id as build_product_id
from sarap_engine.products.raster_io import read_raster


def _metadata_extras(context: PluginContext) -> dict[str, Any]:
    """Mark mock products explicitly. Carry the staged dataset id through to ingest."""
    extra: dict[str, Any] = {"internal_budget_minutes": dict(INTERNAL_BUDGET_MINUTES)}
    if context.execution_mode == "mock":
        extra["mock"] = True
    imagery = context.extras.get("imagery_dataset_id")
    if imagery:
        extra["imagery_dataset_id"] = str(imagery)
    return extra


def _utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def valid_coverage_ratio(nodata: np.ndarray) -> float:
    total = nodata.size
    if total == 0:
        return 0.0
    return float((~np.asarray(nodata, dtype=bool)).sum()) / float(total)


def run_extract(prep: PreprocessResult, profile: AlgoProfile) -> Any:
    p = profile.extract
    return extract_water(
        prep.vv_db,
        vh_db=prep.vh_db,
        incidence=prep.incidence,
        layover=prep.layover,
        nodata=prep.nodata,
        urban=prep.urban,
        slope=prep.slope,
        t_default=p.T_default_vv_db,
        t_clamp=p.T_clamp_vv_db,
        incidence_range=p.incidence_deg,
        slope_deg=p.slope_deg,
        mmu_ha=p.mmu_ha,
        res_m=profile.snap.pixel_spacing_m,
        morph_kernel_px=p.morph_kernel_px,
        use_vh_constraint=p.use_vh_constraint,
        t_vh_bright=p.T_VH_bright_db,
        keep_adjacent_small_patches=p.keep_adjacent_small_patches,
    )


def run_qc(extract_result, profile: AlgoProfile, prep: PreprocessResult):
    return apply_risk_downgrade(
        extract_result.hard_water,
        extract_result.lowconf,
        qc_flags=extract_result.qc_flags,
        nodata=extract_result.nodata,
        urban=prep.urban,
        urban_policy=profile.extract.urban_policy,
        shadow=prep.shadow,
        slope=prep.slope,
        slope_deg=profile.extract.slope_deg,
        layover=prep.layover,
        mark_edge=True,
    )


def _load_baseline(
    context: PluginContext,
    prep: PreprocessResult,
) -> tuple[np.ndarray, np.ndarray, GridSpec] | None:
    """返回 (baseline_water, baseline_valid, baseline_grid)；无本底返回 None。"""
    # 显式声明无本底
    if not context.baseline_version_id and not context.baseline_uri and not context.extras.get("use_synthetic_baseline"):
        return None

    if context.extras.get("use_synthetic_baseline") and "baseline_water" in (prep.extras or {}):
        water = np.asarray(prep.extras["baseline_water"]).astype(bool)
        valid = np.asarray(prep.extras.get("baseline_valid", np.ones(water.shape, dtype=bool))).astype(bool)
        return water, valid, prep.grid

    uri = context.baseline_uri
    if not uri:
        # 有 version_id 但没给栅格路径：视为缺本底数据（业务错误，而不是静默当无本底出 5）
        # 若只给了 version_id 却无 uri，P0 仍允许按无本底出图并标记 baseline_missing。
        return None

    path = Path(uri)
    if not path.exists():
        raise EngineError(ErrorCode.INPUT_MISSING, f"本底栅格不存在: {uri}", retryable=False)
    arr, grid = read_raster(path)
    # 约定：本底 1=水，0=非水；若有 sidecar nodata 则用 grid json；此处用 255/负值为 nodata
    if arr.dtype == np.uint8:
        valid = arr != 255
        water = (arr == 1) & valid
    else:
        valid = np.isfinite(arr) & (arr != 255)
        water = (arr > 0) & valid
    return water, valid, grid


def run_change(context: PluginContext, prep: PreprocessResult, qc_result):
    loaded = _load_baseline(context, prep)
    if loaded is None:
        return classify_without_baseline(
            qc_result.hard_water,
            qc_result.lowconf,
            qc_result.nodata,
            qc_result.qc_flags,
        )
    water, valid, bgrid = loaded
    try:
        assert_grids_aligned(prep.grid, bgrid, require_same_shape=True)
    except GridMisaligned:
        raise
    return classify_with_baseline(
        qc_result.hard_water,
        qc_result.lowconf,
        qc_result.nodata,
        qc_result.qc_flags,
        water,
        valid,
        current_grid=prep.grid,
        baseline_grid=bgrid,
    )


def build_qc_summary(
    *,
    extract_result,
    change_result,
    profile: AlgoProfile,
    coverage: float,
    res_m: float,
    orbit_type: str,
    baseline_version_id: str | None,
    manual_review: bool = False,
) -> dict[str, Any]:
    cm = change_result.class_map
    flags = change_result.qc_flags
    areas = area_stats(cm, res_m=res_m, has_baseline=change_result.has_baseline)
    flag_areas = {name: flag_area_ha(flags, bit, res_m) for bit, name in {
        int(QcFlag.URBAN): "URBAN",
        int(QcFlag.SHADOW): "SHADOW",
        int(QcFlag.LAYOVER): "LAYOVER",
        int(QcFlag.INCIDENCE): "INCIDENCE",
        int(QcFlag.EDGE_MIXED): "EDGE_MIXED",
        int(QcFlag.THIN_OR_SOIL): "THIN_OR_SOIL",
        int(QcFlag.BASELINE_GAP): "BASELINE_GAP",
        int(QcFlag.MMU_REMOVED): "MMU_REMOVED",
        int(QcFlag.ORBIT_DEGRADED): "ORBIT_DEGRADED",
    }.items()}
    thr = extract_result.threshold
    return {
        "threshold_vv_db": thr.T,
        "threshold_vv_source": thr.source,
        "threshold_auto_db": thr.T_auto,
        "threshold_default_db": thr.T_default,
        "threshold_reason": thr.reason,
        "valid_pixel_ratio": coverage,
        "extracted_water_ha": areas.get("extracted_water_ha"),
        "water_current_ha": areas.get("water_current_ha"),
        "flood_event_ha": areas.get("flood_event_ha"),
        "lowconf_ha": areas.get("lowconf_ha"),
        "flag_areas_ha": flag_areas,
        "baseline_version_id": baseline_version_id,
        "orbit_type": orbit_type,
        "coverage_ratio": coverage,
        "flood_event_status": change_result.flood_event_status,
        "manual_review_triggered": manual_review,
        "p0_warnings_block_publish": False,
    }


def build_impact_stats(
    class_map: np.ndarray,
    *,
    res_m: float,
    has_baseline: bool,
    impact_asset_types: list[str],
    grid: GridSpec | None = None,
    impact_assets: Any = None,
    area_name: str = "",
    baseline_version_id: str | None = None,
    acquisition_start: str | None = None,
) -> dict[str, Any]:
    areas = area_stats(class_map, res_m=res_m, has_baseline=has_baseline)
    configured = [
        item
        for item in impact_asset_types
        if item in {"admin_county", "admin_township", "road", "settlement", "cropland"}
    ]
    cross: list[dict[str, Any]] = []
    layers: dict[str, Any] = {}
    note = NO_IMPACT_ASSETS_NOTE
    if configured and grid is not None:
        objects, loaded_note = load_impact_objects(impact_assets, grid)
        if objects:
            cross, layers = overlay_impacts(
                class_map,
                objects,
                grid,
                res_m=res_m,
                has_baseline=has_baseline,
                baseline_version_id=baseline_version_id,
            )
            note = loaded_note or "已在分析网格上叠加道路、居民点与行政区。"
        else:
            note = loaded_note or "已配置影响对象，但没有可叠加的几何，不出交叉结论。"
    elif configured:
        note = "已配置影响对象，但缺少分析网格，不出交叉结论。"
    water_layer = "flood_event_poly" if has_baseline else "water_current_poly"
    layer_names = [water_layer, *layers.keys()]
    emergency = build_emergency_map(
        area_name=area_name,
        crs=grid.crs if grid is not None else "",
        res_m=res_m,
        has_baseline=has_baseline,
        impact_configured=bool(cross or layers),
        cross_stats=cross,
        areas=areas,
        acquisition_start=acquisition_start,
        baseline_version_id=baseline_version_id,
        layer_names=layer_names,
    )
    return {
        "metrics": areas["metrics"],
        "limitation": AREA_LIMITATION,
        "official_note": areas["official_note"],
        "flood_event_status": areas["flood_event_status"],
        "cross_stats": cross,
        "cross_stats_note": note,
        "configured_impact_types": configured,
        "extracted_water_ha": areas.get("extracted_water_ha"),
        "water_current_ha": areas.get("water_current_ha"),
        "flood_event_ha": areas.get("flood_event_ha"),
        "lowconf_ha": areas.get("lowconf_ha"),
        "impact_layers": layers,
        "emergency_map": emergency,
    }


def build_metadata(
    *,
    context: PluginContext,
    change_result,
    extract_result,
    impact: dict[str, Any],
    coverage: float,
    submitted_at: datetime | None,
    processed_at: datetime,
    data_ready_at: datetime | None,
    product_ver: str = "v1",
) -> ProductMetadata:
    pid = build_product_id(
        area_id=context.pilot.region_id,
        s1_product_id=context.scene.s1_product_id,
        scene_id=context.scene.scene_id,
        acquisition_start=context.scene.acquisition_start,
        baseline_version_no=context.baseline_version_id,
        algo_profile_id=context.profile.algo_profile_id,
        prod_ver=product_ver,
    )
    has_baseline = change_result.has_baseline
    extracted_label = EXTRACTED_WATER_AREA_LABEL if not has_baseline else None
    return ProductMetadata(
        product_id=pid,
        area_id=context.pilot.region_id,
        is_pilot=bool(getattr(context.pilot, "is_pilot", False)),
        pilot_id=context.pilot.pilot_id,
        scene_id=context.scene.scene_id,
        scene_code=context.scene.scene_code,
        s1_product_id=context.scene.s1_product_id,
        platform=context.scene.platform,
        mode=context.scene.mode,
        product_level=context.scene.product_level,
        polarizations=list(context.scene.polarizations),
        pass_direction=context.scene.pass_direction,
        ipf_version=context.scene.ipf_version or "",
        orbit_type=context.scene.orbit_type,
        acquisition_start=_utc(context.scene.acquisition_start),
        acquisition_end=_utc(context.scene.acquisition_end),
        processed_at=_utc(processed_at),
        published_at=None,
        sla_minutes=int(getattr(context.pilot, "suggested_target_minutes", None) or context.pilot.sla_minutes or 240),
        suggested_target_minutes=int(getattr(context.pilot, "suggested_target_minutes", None) or context.pilot.sla_minutes or 240),
        external_target_hours=EXTERNAL_TARGET_HOURS,
        contract_commitment=False,
        data_ready_at=_utc(data_ready_at or context.scene.data_ready_at),
        submitted_at=_utc(submitted_at),
        crs=context.pilot.analysis_crs,
        resolution_m=context.profile.snap.pixel_spacing_m,
        grid_origin=[context.pilot.grid.origin_x, context.pilot.grid.origin_y],
        aoi_coverage_ratio=coverage,
        algo_profile_id=context.profile.algo_profile_id,
        snap_version=None,
        threshold_vv_db=extract_result.threshold.T,
        threshold_vv_source=extract_result.threshold.source,
        threshold_default_db=extract_result.threshold.T_default,
        mmu_ha=context.profile.extract.mmu_ha,
        baseline_asset_id=context.baseline_asset_id,
        baseline_version_id=context.baseline_version_id,
        baseline_type=context.baseline_type,
        urban_policy=str(context.profile.extract.urban_policy),
        flood_event_status=change_result.flood_event_status,
        extracted_water_ha=impact.get("extracted_water_ha"),
        extracted_water_area_label=extracted_label,
        water_current_ha=impact.get("water_current_ha") if has_baseline else impact.get("water_current_ha"),
        flood_event_ha=impact.get("flood_event_ha") if has_baseline else None,
        lowconf_ha=impact.get("lowconf_ha"),
        review_status="draft",
        limitations=list(LIMITATIONS),
        param_hash=context.profile.param_hash(),
        extras=_metadata_extras(context),
    )


def run_postprocess(
    context: PluginContext,
    prep: PreprocessResult,
    *,
    submitted_at: datetime | None,
    data_ready_at: datetime | None,
    min_valid_coverage_ratio: float,
    product_ver: str = "v1",
) -> tuple[ProductManifest, dict[str, Any]]:
    coverage = valid_coverage_ratio(prep.nodata)
    if coverage < min_valid_coverage_ratio:
        raise EngineError(
            ErrorCode.COVERAGE_TOO_LOW,
            f"有效覆盖过低: {coverage:.3f} < {min_valid_coverage_ratio}",
            retryable=False,
        )
    extract_result = run_extract(prep, context.profile)
    qc_result = run_qc(extract_result, context.profile, prep)
    change_result = run_change(context, prep, qc_result)
    acq = None
    if context.scene.acquisition_start is not None:
        acq = _utc(context.scene.acquisition_start)
        acq = acq.isoformat() if acq is not None else None
    impact = build_impact_stats(
        change_result.class_map,
        res_m=context.profile.snap.pixel_spacing_m,
        has_baseline=change_result.has_baseline,
        impact_asset_types=context.pilot.impact_assets.configured_types(),
        grid=prep.grid,
        impact_assets=context.pilot.impact_assets,
        area_name=context.pilot.name,
        baseline_version_id=context.baseline_version_id,
        acquisition_start=acq,
    )
    processed_at = datetime.now(timezone.utc)
    qc_summary = build_qc_summary(
        extract_result=extract_result,
        change_result=change_result,
        profile=context.profile,
        coverage=coverage,
        res_m=context.profile.snap.pixel_spacing_m,
        orbit_type=prep.orbit_type,
        baseline_version_id=context.baseline_version_id,
    )
    metadata = build_metadata(
        context=context,
        change_result=change_result,
        extract_result=extract_result,
        impact=impact,
        coverage=coverage,
        submitted_at=submitted_at,
        processed_at=processed_at,
        data_ready_at=data_ready_at,
        product_ver=product_ver,
    )
    out_dir = context.work_dir / "products"
    manifest = package_product(
        out_dir,
        metadata=metadata,
        qc_summary=qc_summary,
        impact_stats=impact,
        class_map=change_result.class_map,
        water_current=change_result.water_current,
        flood_event=change_result.flood_event,
        qc_flags=change_result.qc_flags,
        grid=prep.grid,
    )
    return manifest, {
        "extract": extract_result,
        "qc": qc_result,
        "change": change_result,
        "coverage": coverage,
    }
