"""Published display rasters are tiled, and the GeoPDF stays off unpublished products."""

from __future__ import annotations

import base64
import math
import struct

import numpy as np
from pyproj import Transformer

from tests.conftest import admin_headers, demo_ids, duty_headers, readonly_headers

PDF = b"%PDF-1.4\n1 0 obj<< /Type /Catalog /Pages 2 0 R >>endobj\ntrailer<< /Root 1 0 R >>\n%%EOF\n/Subtype /GEO\n"


def _tile_index(lon: float, lat: float, z: int) -> tuple[int, int]:
    n = 2**z
    x = int((lon + 180.0) / 360.0 * n)
    lat_rad = math.radians(lat)
    y = int((1.0 - math.log(math.tan(lat_rad) + 1.0 / math.cos(lat_rad)) / math.pi) / 2.0 * n)
    return x, y


def _display(area) -> dict:
    lon, lat = 116.5, 39.9
    transformer = Transformer.from_crs("EPSG:4326", area.analysis_crs, always_xy=True)
    east, north = transformer.transform(lon, lat)
    res = 10.0
    origin_x = float(east) - 40.0
    origin_y = float(north) + 40.0
    rgba = np.zeros((8, 8, 4), dtype=np.uint8)
    rgba[4, 4] = (196, 92, 38, 230)
    return {
        "crs": area.analysis_crs,
        "transform": [origin_x, res, 0.0, origin_y, 0.0, -res],
        "width": 8,
        "height": 8,
        "samples": 4,
        "encoding": "rgba-raw",
        "pixels_b64": base64.b64encode(rgba.tobytes()).decode("ascii"),
    }


def _create(client, headers, project, area):
    return client.post(
        "/api/v1/products",
        headers=headers,
        json={
            "project_id": str(project.id),
            "area_id": str(area.id),
            "scene_code": "flood",
            "product_type": "SARAP_FLOOD_V1",
            "title": "栅格应急图",
            "extracted_water_ha": 1.0,
            "metadata_json": {"crs": area.analysis_crs},
            "artifacts_json": [
                {
                    "layer_key": "water_current",
                    "media_type": "image/tiff",
                    "storage_uri": "file:///water_current_display.tif",
                    "metadata_json": {"crs": area.analysis_crs, "display": _display(area)},
                },
                {
                    "layer_key": "thematic_map_pdf",
                    "media_type": "application/pdf",
                    "storage_uri": "file:///thematic_map.pdf",
                    "metadata_json": {"pdf_b64": base64.b64encode(PDF).decode("ascii")},
                },
            ],
        },
    )


def test_published_product_serves_tiles_cog_and_geopdf(client, db):
    duty = duty_headers(client)
    admin = admin_headers(client)
    ro = readonly_headers(client)
    _, project, area = demo_ids(db)
    created = _create(client, duty, project, area)
    assert created.status_code == 201, created.text
    product_id = created.json()["data"]["id"]

    assert client.get(f"/api/v1/products/{product_id}/emergency-map.pdf", headers=duty).status_code == 404
    assert client.get(
        f"/api/v1/products/{product_id}/layers/water_current/tiles/16/0/0.png",
        headers=ro,
    ).status_code == 404

    assert client.post(f"/api/v1/products/{product_id}/publish", json={}, headers=duty).status_code == 200

    mapped = client.get(
        "/api/v1/products/map",
        params={"area_id": str(area.id), "project_id": str(project.id)},
        headers=ro,
    )
    assert mapped.status_code == 200, mapped.text
    shown = next(item for item in mapped.json()["data"]["products"] if item["id"] == product_id)
    assert shown["rasters"][0]["layer_key"] == "water_current"
    assert shown["rasters"][0]["kind"] == "water"
    assert "{z}" in shown["rasters"][0]["tile_template"]
    assert shown["geopdf_path"].endswith("/emergency-map.pdf")
    assert shown["flood_event_status"] == "baseline_missing"

    zx, zy = _tile_index(116.5, 39.9, 16)
    tile = client.get(
        f"/api/v1/products/{product_id}/layers/water_current/tiles/16/{zx}/{zy}.png",
        headers=ro,
    )
    assert tile.status_code == 200, tile.text
    assert tile.headers["content-type"].startswith("image/png")
    assert tile.content.startswith(b"\x89PNG")

    missed = client.get(
        f"/api/v1/products/{product_id}/layers/water_current/tiles/4/0/0.png",
        headers=duty,
    )
    assert missed.status_code == 200
    assert missed.content != tile.content

    cog = client.get(f"/api/v1/products/{product_id}/layers/water_current/cog", headers=ro)
    assert cog.status_code == 200
    assert cog.content[:2] == b"II"
    assert cog.headers["accept-ranges"] == "bytes"
    partial = client.get(
        f"/api/v1/products/{product_id}/layers/water_current/cog",
        headers={**ro, "Range": "bytes=0-7"},
    )
    assert partial.status_code == 206
    assert partial.content == cog.content[:8]

    hit = client.get(
        f"/api/v1/products/{product_id}/identify",
        params={"lon": 116.5, "lat": 39.9},
        headers=duty,
    )
    assert hit.status_code == 200, hit.text
    assert hit.json()["data"]["hits"][0]["title"] == "提取水体（未扣本底）"
    miss = client.get(
        f"/api/v1/products/{product_id}/identify",
        params={"lon": 0, "lat": 0},
        headers=duty,
    )
    assert miss.json()["data"]["hits"] == []

    pdf = client.get(f"/api/v1/products/{product_id}/emergency-map.pdf", headers=duty)
    assert pdf.status_code == 200
    assert pdf.headers["content-type"].startswith("application/pdf")
    assert pdf.content.startswith(b"%PDF")
    assert b"/Subtype /GEO" in pdf.content
    preview = client.get(
        "/api/v1/briefings/preview/emergency-map.pdf",
        params={"project_id": str(project.id), "area_id": str(area.id), "scene_code": "flood"},
        headers=ro,
    )
    assert preview.status_code == 200, preview.text
    assert preview.content.startswith(b"%PDF")

    assert client.post(
        f"/api/v1/products/{product_id}/withdraw",
        json={"reason": "撤"},
        headers=admin,
    ).status_code == 200
    assert client.get(f"/api/v1/products/{product_id}/emergency-map.pdf", headers=admin).status_code == 404
    again = client.get("/api/v1/products/map", params={"area_id": str(area.id)}, headers=ro)
    assert product_id not in {item["id"] for item in again.json()["data"]["products"]}


def test_cog_geokey_matches_analysis_crs(client, db):
    duty = duty_headers(client)
    _, project, area = demo_ids(db)
    created = _create(client, duty, project, area)
    product_id = created.json()["data"]["id"]
    assert client.post(f"/api/v1/products/{product_id}/publish", json={}, headers=duty).status_code == 200
    cog = client.get(f"/api/v1/products/{product_id}/layers/water_current/cog", headers=duty)
    assert cog.status_code == 200
    blob = cog.content
    offset = struct.unpack_from("<I", blob, 4)[0]
    count = struct.unpack_from("<H", blob, offset)[0]
    geokey = b""
    for index in range(count):
        entry = offset + 2 + 12 * index
        code, _typ, n, raw = struct.unpack_from("<HHI4s", blob, entry)
        if code == 34735:
            nbytes = n * 2
            ptr = struct.unpack("<I", raw)[0]
            geokey = blob[ptr : ptr + nbytes]
    epsg = int(str(area.analysis_crs).split(":")[-1])
    assert epsg in struct.unpack("<" + "H" * (len(geokey) // 2), geokey)
