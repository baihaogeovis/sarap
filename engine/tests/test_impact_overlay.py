"""Impact overlay on the analysis grid, using the compact public-validation fixture."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from pyproj import Transformer

from sarap_engine.algo.grid import GridSpec
from sarap_engine.algo.impact import load_impact_objects, overlay_impacts
from sarap_engine.constants import ClassCode
from sarap_engine.fixtures.loader import PUBLIC_VALIDATION_FIXTURE
from sarap_engine.plugins.snap.workflows.pipeline import build_impact_stats


def _window_grid(**kwargs) -> GridSpec:
    defaults = dict(crs="EPSG:4548", res_m=10, origin_x=0, origin_y=0, width=80, height=80)
    defaults.update(kwargs)
    return GridSpec(**defaults)


def _open_water_map() -> np.ndarray:
    """West-side open water, with a low-confidence block where the urban settlement sits."""
    grid = np.full((80, 80), int(ClassCode.NON_WATER), dtype=np.uint8)
    grid[:, 0:18] = int(ClassCode.PERMANENT_OR_BASELINE_WATER)
    grid[:, 18:30] = int(ClassCode.FLOOD_EVENT)
    grid[20:35, 10:25] = int(ClassCode.WATER_LOWCONF)
    return grid


def _assets() -> dict[str, str]:
    token = PUBLIC_VALIDATION_FIXTURE
    return {
        "admin_county": token,
        "admin_township": token,
        "road": token,
        "settlement": token,
    }


def _rows(stats: list[dict], object_id: str, metric: str, scope: str = "default") -> list[dict]:
    return [
        row
        for row in stats
        if row["object_id"] == object_id and row["metric"] == metric and row["scope"] == scope
    ]


def test_fixture_overlay_hits_open_water_and_skips_dry_ground():
    grid = _window_grid()
    objects, note = load_impact_objects(_assets(), grid)
    assert objects
    assert "分析网格" in (note or "")
    rows, layers = overlay_impacts(
        _open_water_map(),
        objects,
        grid,
        res_m=10,
        has_baseline=True,
        baseline_version_id="v-test",
    )
    road = _rows(rows, "rd-cross", "affected_length_m")
    assert road and 200 < road[0]["value"] < 700
    assert _rows(rows, "rd-dry", "affected_length_m") == []
    flooded = _rows(rows, "st-flood", "affected_area_ha")
    assert flooded and 1.0 <= flooded[0]["value"] <= 1.6
    assert _rows(rows, "st-dry", "affected_area_ha") == []
    assert _rows(rows, "st-urban", "affected_area_ha") == []
    urban_low = _rows(rows, "st-urban", "affected_area_ha", "including_lowconf")
    assert urban_low and urban_low[0]["value"] > 0
    assert _rows(rows, "county-west", "affected_area_ha")
    assert _rows(rows, "county-east", "affected_area_ha") == []
    assert _rows(rows, "township-river", "affected_area_ha")
    assert _rows(rows, "township-dry", "affected_area_ha") == []
    assert all(row["extra"]["basis"] == "flood_event" for row in rows)
    assert all("depth" not in row["metric"] for row in rows)

    road_layer = layers["impact_road"]
    assert road_layer["crs"] == "EPSG:4548"
    flat = [value for feature in road_layer["features"] for pt in feature["geometry"]["coordinates"] for value in pt]
    assert any(abs(value) > 90 for value in flat)


def test_without_assets_there_are_no_cross_stats():
    stats = build_impact_stats(
        _open_water_map(),
        res_m=10,
        has_baseline=True,
        impact_asset_types=[],
        grid=_window_grid(),
    )
    assert stats["cross_stats"] == []
    assert "未配置影响对象" in stats["cross_stats_note"]
    assert stats["emergency_map"]["impact_configured"] is False
    assert stats["emergency_map"]["summary"] == {}


def test_web_mercator_is_not_used_for_the_overlay():
    stats = build_impact_stats(
        _open_water_map(),
        res_m=10,
        has_baseline=True,
        impact_asset_types=["road", "settlement", "admin_county"],
        grid=_window_grid(crs="EPSG:3857"),
        impact_assets=_assets(),
    )
    assert stats["cross_stats"] == []
    assert "Web Mercator" in stats["cross_stats_note"]
    assert stats["impact_layers"] == {}


def test_geographic_geojson_is_reprojected_into_the_analysis_crs(tmp_path: Path):
    transformer = Transformer.from_crs("EPSG:4326", "EPSG:4548", always_xy=True)
    origin_x, origin_y = transformer.transform(116.4, 39.82)
    grid = GridSpec(crs="EPSG:4548", res_m=10, origin_x=float(origin_x), origin_y=float(origin_y), width=30, height=30)
    doc = {
        "type": "FeatureCollection",
        "crs": "EPSG:4326",
        "features": [
            {
                "type": "Feature",
                "properties": {
                    "object_type": "admin_county",
                    "object_id": "county-ll",
                    "object_name": "窗口县",
                    "parent_admin_code": "",
                },
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[116.35, 39.75], [116.45, 39.75], [116.45, 39.85], [116.35, 39.85], [116.35, 39.75]]],
                },
            }
        ],
    }
    path = tmp_path / "county.geojson"
    path.write_text(json.dumps(doc), encoding="utf-8")
    class_map = np.full((30, 30), int(ClassCode.FLOOD_EVENT), dtype=np.uint8)
    stats = build_impact_stats(
        class_map,
        res_m=10,
        has_baseline=True,
        impact_asset_types=["admin_county"],
        grid=grid,
        impact_assets={"admin_county": str(path)},
        area_name="示例区域",
    )
    hit = _rows(stats["cross_stats"], "county-ll", "affected_area_ha")
    assert hit and hit[0]["value"] > 0
    feature = stats["impact_layers"]["impact_admin_poly"]["features"][0]
    xs = [pt[0] for pt in feature["geometry"]["coordinates"][0]]
    assert max(xs) > 1000  # metres in the analysis CRS, not degrees
    assert stats["emergency_map"]["basis_label"] == "本次淹没"
    assert stats["emergency_map"]["contract_commitment"] is False
    assert stats["emergency_map"]["suggested_target_minutes"] == 240
