"""Display COG and emergency GeoPDF, without SNAP or GDAL."""

from __future__ import annotations

import base64
import struct
from pathlib import Path

import numpy as np

from sarap_engine.algo.grid import GridSpec
from sarap_engine.products.cog import encode_rgba_cog
from sarap_engine.products.exporters import package_product
from sarap_engine.products.geopdf import build_emergency_geopdf
from sarap_engine.products.ingest import IngestClient
from sarap_engine.products.models import ProductMetadata


def _read_ifd(blob: bytes) -> dict[int, tuple[int, int, bytes]]:
    assert blob[:2] == b"II"
    assert struct.unpack_from("<H", blob, 2)[0] == 42
    offset = struct.unpack_from("<I", blob, 4)[0]
    count = struct.unpack_from("<H", blob, offset)[0]
    tags: dict[int, tuple[int, int, bytes]] = {}
    for index in range(count):
        entry = offset + 2 + 12 * index
        code, typ, n, raw = struct.unpack_from("<HHI4s", blob, entry)
        tags[code] = (typ, n, raw)
    return tags


def _tag_bytes(blob: bytes, tags: dict[int, tuple[int, int, bytes]], code: int, type_size: int) -> bytes:
    typ, count, raw = tags[code]
    nbytes = count * type_size
    if nbytes <= 4:
        return raw[:nbytes]
    offset = struct.unpack("<I", raw)[0]
    return blob[offset : offset + nbytes]


def test_rgba_cog_is_tiled_and_georeferenced():
    rgba = np.zeros((6, 8, 4), dtype=np.uint8)
    rgba[1, 2] = (196, 92, 38, 230)
    blob = encode_rgba_cog(rgba, crs="EPSG:4548", origin_x=500000, origin_y=4420000, res_x=10, res_y=10)
    tags = _read_ifd(blob)
    assert tags[259][2][:2] == struct.pack("<H", 1)  # uncompressed
    assert struct.unpack("<I", tags[322][2])[0] == 256
    scale = struct.unpack("<ddd", _tag_bytes(blob, tags, 33550, 8))
    assert scale[0] == 10 and scale[1] == 10
    tie = struct.unpack("<dddddd", _tag_bytes(blob, tags, 33922, 8))
    assert tie[3] == 500000 and tie[4] == 4420000
    keys = struct.unpack("<" + "H" * (len(_tag_bytes(blob, tags, 34735, 2)) // 2), _tag_bytes(blob, tags, 34735, 2))
    assert 4548 in keys
    tile_off = struct.unpack("<I", tags[273][2])[0]
    pixel = blob[tile_off + (1 * 256 + 2) * 4 : tile_off + (1 * 256 + 2) * 4 + 4]
    assert pixel == bytes((196, 92, 38, 230))


def test_geopdf_carries_wgs84_corners():
    rgba = np.zeros((4, 4, 4), dtype=np.uint8)
    rgba[:, :2] = (196, 92, 38, 230)
    grid = GridSpec(crs="EPSG:4548", res_m=10, origin_x=500000, origin_y=4420000, width=4, height=4)
    pdf = build_emergency_geopdf(
        rgba,
        grid,
        emergency={"title": "示例区域洪水应急图", "basis_label": "本次淹没", "crs": "EPSG:4548", "inundation_ha": 6.75},
        impact_layers=None,
        product_id="P-demo",
    )
    assert pdf.startswith(b"%PDF")
    text = pdf.decode("latin1")
    assert "/Subtype /GEO" in text
    assert "/GPTS" in text
    assert "示例区域" not in text  # Chinese is rasterized, not a PDF font
    # False easting 500 km on the 117E belt is near 117E, 40N.
    assert "39." in text or "40." in text
    assert "116." in text or "117." in text


def test_package_embeds_display_and_geopdf(tmp_path: Path):
    grid = GridSpec(crs="EPSG:4548", res_m=10, origin_x=500000, origin_y=4420000, width=4, height=4)
    class_map = np.zeros((4, 4), dtype=np.uint8)
    class_map[:, :2] = 3
    class_map[:, 2:] = 2
    water = np.ones((4, 4), dtype=np.uint8)
    flood = (class_map == 3).astype(np.uint8)
    meta = ProductMetadata(
        product_id="P-cog",
        flood_event_status="computed",
        crs="EPSG:4548",
        resolution_m=10,
        flood_event_ha=0.02,
        water_current_ha=0.04,
        baseline_version_id="11111111-1111-1111-1111-111111111111",
    )
    manifest = package_product(
        tmp_path,
        metadata=meta,
        qc_summary={"warnings": []},
        impact_stats={"metrics": [], "emergency_map": {"title": "示例区域洪水应急图", "basis_label": "本次淹没", "crs": "EPSG:4548"}},
        class_map=class_map,
        water_current=water,
        flood_event=flood,
        qc_flags=np.zeros((4, 4), dtype=np.uint16),
        grid=grid,
    )
    names = {layer.name for layer in manifest.layers}
    assert "baseline_water" in names
    assert "thematic_map_pdf" in names
    assert (tmp_path / "flood_event_display.tif").is_file()
    assert (tmp_path / "thematic_map.pdf").is_file()
    payload = IngestClient("http://localhost", mode="mock").build_product_payload("job", manifest, task_id="task")
    flood_layer = next(item for item in payload["artifacts_json"] if item["layer_key"] == "flood_event")
    display = flood_layer["metadata_json"]["display"]
    raw = base64.b64decode(display["pixels_b64"])
    assert len(raw) == 4 * 4 * 4
    assert display["crs"] == "EPSG:4548"
    pdf_layer = next(item for item in payload["artifacts_json"] if item["layer_key"] == "thematic_map_pdf")
    pdf = base64.b64decode(pdf_layer["metadata_json"]["pdf_b64"])
    assert pdf.startswith(b"%PDF")
    assert "/Subtype /GEO" in pdf.decode("latin1")
