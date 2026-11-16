from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.conftest import admin_headers, demo_ids, duty_headers, readonly_headers


def _draft(client: TestClient, db: Session, headers: dict, **extra) -> dict:
    _, project, area = demo_ids(db)
    payload = {
        "project_id": str(project.id),
        "area_id": str(area.id),
        "scene_code": "flood",
        "product_type": "SARAP_FLOOD_V1",
        "title": "准范围草稿",
        "extracted_water_ha": 12.34,
        "artifacts_json": [
            {"layer_key": "class_map", "media_type": "image/tiff", "storage_uri": "file://class_map.tif"},
            {"layer_key": "water_current", "media_type": "image/tiff", "storage_uri": "file://water.tif"},
            {"layer_key": "flood_event", "media_type": "image/tiff", "storage_uri": "file://should_omit.tif"},
        ],
    }
    payload.update(extra)
    resp = client.post("/api/v1/products", json=payload, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()["data"]


def test_duty_officer_can_short_publish_and_qc_but_not_withdraw(client, db):
    duty = duty_headers(client)
    admin = admin_headers(client)
    product = _draft(client, db, duty)
    assert product["status"] == "draft"
    assert product["flood_event_status"] == "baseline_missing"
    assert product["extracted_water_ha"] == 12.34
    assert product["flood_event_ha"] is None

    # P0 short publish: draft -> published, no pending_qc required.
    published = client.post(f"/api/v1/products/{product['id']}/publish", json={}, headers=duty)
    assert published.status_code == 200, published.text
    assert published.json()["data"]["status"] == "published"

    # duty cannot withdraw
    withdrawn = client.post(
        f"/api/v1/products/{product['id']}/withdraw",
        json={"reason": "试撤"},
        headers=duty,
    )
    assert withdrawn.status_code == 403

    # admin can withdraw
    ok = client.post(
        f"/api/v1/products/{product['id']}/withdraw",
        json={"reason": "数据更新"},
        headers=admin,
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["data"]["status"] == "withdrawn"

    # P1 QC path still works for duty: new draft -> submit -> reject (reason required) -> submit -> publish
    other = _draft(client, db, duty, title="待质检")
    submitted = client.post(f"/api/v1/products/{other['id']}/submit", json={}, headers=duty)
    assert submitted.status_code == 200
    assert submitted.json()["data"]["status"] == "pending_qc"
    missing = client.post(f"/api/v1/products/{other['id']}/reject", json={}, headers=duty)
    assert missing.status_code == 422
    rejected = client.post(
        f"/api/v1/products/{other['id']}/reject",
        json={"reason": "建成区误提偏多，需复核"},
        headers=duty,
    )
    assert rejected.status_code == 200, rejected.text
    body = rejected.json()["data"]
    assert body["status"] == "draft"
    assert "建成区" in body["reject_reason"]
    # Not withdrawn
    assert body["withdrawn_at"] is None


def test_readonly_sees_only_published(client, db):
    duty = duty_headers(client)
    ro = readonly_headers(client)
    draft = _draft(client, db, duty, title="只读不可见")
    hidden = client.get(f"/api/v1/products/{draft['id']}", headers=ro)
    assert hidden.status_code == 404
    listed = client.get("/api/v1/products", headers=ro)
    assert listed.status_code == 200
    assert all(item["status"] == "published" for item in listed.json()["data"])
    assert draft["id"] not in {item["id"] for item in listed.json()["data"]}

    client.post(f"/api/v1/products/{draft['id']}/publish", json={}, headers=duty)
    visible = client.get(f"/api/v1/products/{draft['id']}", headers=ro)
    assert visible.status_code == 200
    assert visible.json()["data"]["status"] == "published"

    # withdrawn hidden from readonly and default one-map
    admin = admin_headers(client)
    client.post(f"/api/v1/products/{draft['id']}/withdraw", json={"reason": "撤"}, headers=admin)
    assert client.get(f"/api/v1/products/{draft['id']}", headers=ro).status_code == 404
    mapped = client.get("/api/v1/products?for_map=true", headers=admin)
    assert draft["id"] not in {item["id"] for item in mapped.json()["data"]}


def test_withdrawn_requires_new_version_and_re_qc(client, db):
    duty = duty_headers(client)
    admin = admin_headers(client)
    product = _draft(client, db, duty)
    client.post(f"/api/v1/products/{product['id']}/publish", json={}, headers=duty)
    # cannot edit published in place
    patch = client.patch(
        f"/api/v1/products/{product['id']}",
        json={
            "project_id": product["project_id"],
            "product_type": "SARAP_FLOOD_V1",
            "title": "篡改",
        },
        headers=admin,
    )
    assert patch.status_code == 409

    client.post(f"/api/v1/products/{product['id']}/withdraw", json={"reason": "撤"}, headers=admin)
    # cannot republish the withdrawn row
    again = client.post(f"/api/v1/products/{product['id']}/publish", json={}, headers=duty)
    assert again.status_code == 409

    created = client.post(f"/api/v1/products/{product['id']}/new-version", json={}, headers=duty)
    assert created.status_code == 201, created.text
    clone = created.json()["data"]
    assert clone["status"] == "draft"
    assert clone["version"] == product["version"] + 1
    assert clone["re_qc_required"] is True
    # short publish is blocked; must re-QC
    blocked = client.post(f"/api/v1/products/{clone['id']}/publish", json={}, headers=duty)
    assert blocked.status_code == 409
    client.post(f"/api/v1/products/{clone['id']}/submit", json={}, headers=duty)
    published = client.post(f"/api/v1/products/{clone['id']}/publish", json={}, headers=duty)
    assert published.status_code == 200
    assert published.json()["data"]["status"] == "published"


def test_layers_and_area_labels_without_baseline(client, db):
    duty = duty_headers(client)
    product = _draft(client, db, duty)
    layers = client.get(f"/api/v1/products/{product['id']}/layers", headers=duty)
    assert layers.status_code == 200
    meta = layers.json()["meta"]
    assert "flood_event" not in meta["layer_keys"]
    assert "extracted_water" in meta["class_map"].values()
    keys = {row["layer_key"] for row in layers.json()["data"]}
    assert "flood_event" not in keys
    stats = client.get(f"/api/v1/products/{product['id']}/stats", headers=duty)
    assert stats.status_code == 200
    metrics = {row["metric"]: row for row in stats.json()["meta"]["area_metrics"]}
    assert metrics["extracted_water_ha"]["label"] == "提取水体面积（未扣本底）"
    # P1 cross stats are not fabricated
    types = {row["object_type"] for row in stats.json()["data"]}
    assert "admin_county" not in types
    assert "road" not in types
    assert "settlement" not in types


def test_depth_fields_rejected(client, db):
    duty = duty_headers(client)
    _, project, area = demo_ids(db)
    resp = client.post(
        "/api/v1/products",
        json={
            "project_id": str(project.id),
            "area_id": str(area.id),
            "product_type": "SARAP_FLOOD_V1",
            "title": "非法水深",
            "metadata_json": {"water_depth_m": 1.2},
        },
        headers=duty,
    )
    assert resp.status_code == 422
