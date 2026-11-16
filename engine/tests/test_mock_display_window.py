"""Mock products place a displayable vector on the area AOI and post it back."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient
from pyproj import Transformer

from tests.test_platform_mock_duty import _app, _platform_job, _settings


def _vertices(collection: dict) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []

    def walk(coords):
        if isinstance(coords, list) and coords and isinstance(coords[0], (int, float)):
            points.append((float(coords[0]), float(coords[1])))
            return
        if isinstance(coords, list):
            for item in coords:
                walk(item)

    for feature in collection.get("features") or []:
        walk((feature.get("geometry") or {}).get("coordinates"))
    return points


def _assert_on_aoi(collection: dict, analysis_crs: str):
    inverse = Transformer.from_crs(analysis_crs, "EPSG:4326", always_xy=True)
    vertices = _vertices(collection)
    assert vertices, collection
    for x, y in vertices:
        lon, lat = inverse.transform(x, y)
        assert 116.15 <= lon <= 116.85, (lon, lat, analysis_crs)
        assert 39.55 <= lat <= 40.15, (lon, lat, analysis_crs)


def test_mock_window_follows_area_crs_and_ingest_embeds_geojson(tmp_path):
    cases = (
        ("EPSG:32650", 500000.0, 4400000.0),
        ("EPSG:4548", 0.0, 0.0),
    )
    for crs, origin_x, origin_y in cases:
        work = tmp_path / crs.replace(":", "_")
        work.mkdir()
        app = _app(_settings(work))
        client = TestClient(app)
        body = _platform_job(
            baseline_version_id="55555555-5555-4555-8555-555555555555",
            task_id="66666666-6666-4666-8666-666666666666",
        )
        body["pilot"]["analysis_crs"] = crs
        body["pilot"]["grid"] = {"res_m": 10, "origin_x": origin_x, "origin_y": origin_y}
        body["params"]["analysis_crs"] = crs
        resp = client.post("/internal/engine/jobs", json=body)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["status"] == "succeeded", data.get("error_message")
        meta = data["product"]["metadata"]
        assert meta["crs"] == crs
        assert meta["grid_origin"] == [origin_x, origin_y]
        assert meta["flood_event_status"] == "computed"
        layers = {layer["name"]: layer for layer in data["product"]["layers"]}
        flood = json.loads(Path(layers["flood_event_poly"]["uri"]).read_text(encoding="utf-8"))
        water = json.loads(Path(layers["water_current_poly"]["uri"]).read_text(encoding="utf-8"))
        assert flood["features"]
        _assert_on_aoi(flood, crs)
        _assert_on_aoi(water, crs)
        # The stored grid origin is the alignment reference, not the patch itself.
        xs = [point[0] for point in _vertices(flood)]
        if origin_x == 0:
            assert min(xs) > 1000
        calls = [call for call in app.state.worker.ingest_client.calls if str(call["url"]).endswith("/products")]
        assert calls
        artifacts = {item["layer_key"]: item for item in calls[-1]["body"]["artifacts_json"]}
        embedded = artifacts["flood_event_poly"]["metadata_json"]
        assert embedded["crs"] == crs
        assert embedded["geojson"]["type"] == "FeatureCollection"
        assert embedded["geojson"]["features"]
        assert "flood_event_poly" in artifacts
