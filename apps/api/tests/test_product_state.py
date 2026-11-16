from __future__ import annotations

from tests.conftest import auth_header, login


def _create_draft(client, headers, title="淹没范围"):
    projects = client.get("/api/v1/projects", headers=headers)
    project_id = projects.json()["data"][0]["id"]
    created = client.post(
        "/api/v1/products",
        headers=headers,
        json={"project_id": project_id, "scene_code": "flood", "product_type": "SARAP_FLOOD_V1", "title": title},
    )
    assert created.status_code == 201
    return created.json()["data"]


def test_full_lifecycle_and_audit(client):
    admin = auth_header(login(client, "admin@sarap.local", "admin123"))
    product = _create_draft(client, admin)
    product_id = product["id"]
    assert product["status"] == "draft"
    assert product["version"] == 1

    submitted = client.post(f"/api/v1/products/{product_id}/submit", headers=admin, json={})
    assert submitted.json()["data"]["status"] == "pending_qc"

    rejected = client.post(f"/api/v1/products/{product_id}/reject", headers=admin, json={"comment": "范围需复核"})
    assert rejected.json()["data"]["status"] == "draft"
    assert "范围需复核" in rejected.json()["data"]["review_comment"]

    client.post(f"/api/v1/products/{product_id}/submit", headers=admin, json={})
    published = client.post(f"/api/v1/products/{product_id}/publish", headers=admin, json={"comment": "通过"})
    assert published.json()["data"]["status"] == "published"
    assert published.json()["data"]["published_at"] is not None

    # Cannot mutate a published row in place.
    patched = client.patch(
        f"/api/v1/products/{product_id}",
        headers=admin,
        json={
            "project_id": published.json()["data"]["project_id"],
            "product_type": "SARAP_FLOOD_V1",
            "title": "试图改已发布产品",
        },
    )
    assert patched.status_code == 409
    assert patched.json()["error"]["code"] == "immutable_product"

    # Cannot skip withdraw and go back to draft.
    illegal = client.post(f"/api/v1/products/{product_id}/reject", headers=admin, json={"comment": "不可退回已发布产品"})
    assert illegal.status_code == 409

    withdrawn = client.post(f"/api/v1/products/{product_id}/withdraw", headers=admin, json={"reason": "换本底重跑"})
    assert withdrawn.json()["data"]["status"] == "withdrawn"

    # Cannot republish the withdrawn row.
    republish = client.post(f"/api/v1/products/{product_id}/publish", headers=admin, json={})
    assert republish.status_code == 409

    clone = client.post(f"/api/v1/products/{product_id}/new-version", headers=admin)
    assert clone.status_code == 201
    assert clone.json()["data"]["status"] == "draft"
    assert clone.json()["data"]["version"] == 2
    assert clone.json()["data"]["id"] != product_id


def test_readonly_sees_only_published(client):
    admin = auth_header(login(client, "admin@sarap.local", "admin123"))
    draft = _create_draft(client, admin, title="草稿不可见")
    published = _create_draft(client, admin, title="已发布可见")
    client.post(f"/api/v1/products/{published['id']}/submit", headers=admin, json={})
    client.post(f"/api/v1/products/{published['id']}/publish", headers=admin, json={})

    readonly = auth_header(login(client, "readonly@sarap.local", "readonly123"))
    listing = client.get("/api/v1/products", headers=readonly)
    ids = {item["id"] for item in listing.json()["data"]}
    assert published["id"] in ids
    assert draft["id"] not in ids

    hidden = client.get(f"/api/v1/products/{draft['id']}", headers=readonly)
    assert hidden.status_code == 404
