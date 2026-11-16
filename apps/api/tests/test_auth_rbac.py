from __future__ import annotations

from tests.conftest import auth_header, login


def test_login_success(client):
    token = login(client, "admin@sarap.local", "admin123")
    me = client.get("/api/v1/auth/me", headers=auth_header(token))
    assert me.status_code == 200
    body = me.json()
    assert body["error"] is None
    assert body["data"]["email"] == "admin@sarap.local"
    assert "admin" in body["data"]["roles"]


def test_unauthenticated_rejected(client):
    response = client.get("/api/v1/projects")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


def test_bad_password_rejected(client):
    response = client.post("/api/v1/auth/login", json={"email": "admin@sarap.local", "password": "wrong"})
    assert response.status_code == 401


def test_readonly_cannot_create_task(client):
    token = login(client, "readonly@sarap.local", "readonly123")
    projects = client.get("/api/v1/projects", headers=auth_header(token))
    project_id = projects.json()["data"][0]["id"]
    response = client.post(
        "/api/v1/tasks",
        headers=auth_header(token),
        json={
            "project_id": project_id,
            "scene_code": "flood",
            "task_type": "flood_pipeline",
            "title": "不应创建",
        },
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"


def test_readonly_cannot_publish(client):
    admin = auth_header(login(client, "admin@sarap.local", "admin123"))
    projects = client.get("/api/v1/projects", headers=admin)
    project_id = projects.json()["data"][0]["id"]
    created = client.post(
        "/api/v1/products",
        headers=admin,
        json={"project_id": project_id, "scene_code": "flood", "product_type": "SARAP_FLOOD_V1", "title": "淹没范围草稿"},
    )
    product_id = created.json()["data"]["id"]
    client.post(f"/api/v1/products/{product_id}/submit", headers=admin, json={})
    readonly = auth_header(login(client, "readonly@sarap.local", "readonly123"))
    response = client.post(f"/api/v1/products/{product_id}/publish", headers=readonly, json={})
    assert response.status_code == 403


def test_duty_can_qc_and_publish(client):
    duty = auth_header(login(client, "duty@sarap.local", "duty123"))
    projects = client.get("/api/v1/projects", headers=duty)
    project_id = projects.json()["data"][0]["id"]
    created = client.post(
        "/api/v1/products",
        headers=duty,
        json={"project_id": project_id, "scene_code": "flood", "product_type": "SARAP_FLOOD_V1", "title": "值班员发布"},
    )
    assert created.status_code == 201
    product_id = created.json()["data"]["id"]
    submitted = client.post(f"/api/v1/products/{product_id}/submit", headers=duty, json={})
    assert submitted.status_code == 200
    assert submitted.json()["data"]["status"] == "pending_qc"
    published = client.post(f"/api/v1/products/{product_id}/publish", headers=duty, json={"comment": "通过"})
    assert published.status_code == 200
    assert published.json()["data"]["status"] == "published"


def test_duty_cannot_manage_members(client):
    duty = auth_header(login(client, "duty@sarap.local", "duty123"))
    admin = auth_header(login(client, "admin@sarap.local", "admin123"))
    projects = client.get("/api/v1/projects", headers=admin)
    project_id = projects.json()["data"][0]["id"]
    me = client.get("/api/v1/auth/me", headers=duty)
    user_id = me.json()["data"]["id"]
    response = client.post(
        f"/api/v1/projects/{project_id}/members",
        headers=duty,
        json={"user_id": user_id, "role_code": "admin"},
    )
    assert response.status_code == 403


def test_duty_cannot_withdraw(client):
    duty = auth_header(login(client, "duty@sarap.local", "duty123"))
    projects = client.get("/api/v1/projects", headers=duty)
    project_id = projects.json()["data"][0]["id"]
    created = client.post(
        "/api/v1/products",
        headers=duty,
        json={"project_id": project_id, "scene_code": "flood", "product_type": "SARAP_FLOOD_V1", "title": "待撤回"},
    )
    product_id = created.json()["data"]["id"]
    client.post(f"/api/v1/products/{product_id}/submit", headers=duty, json={})
    client.post(f"/api/v1/products/{product_id}/publish", headers=duty, json={})
    withdrawn = client.post(f"/api/v1/products/{product_id}/withdraw", headers=duty, json={"reason": "误发"})
    assert withdrawn.status_code == 403


def test_org_id_in_body_is_ignored(client):
    admin = auth_header(login(client, "admin@sarap.local", "admin123"))
    me = client.get("/api/v1/auth/me", headers=admin)
    real_org = me.json()["data"]["org_id"]
    fake = "00000000-0000-0000-0000-000000000099"
    response = client.post(
        "/api/v1/projects",
        headers=admin,
        json={"code": "other-pilot", "name": "另一试点", "org_id": fake, "default_crs": "EPSG:4547"},
    )
    assert response.status_code == 201
    assert response.json()["data"]["org_id"] == real_org
    assert response.json()["data"]["org_id"] != fake


def test_engine_down_fails_clearly(client, engine_client):
    admin = auth_header(login(client, "admin@sarap.local", "admin123"))
    projects = client.get("/api/v1/projects", headers=admin)
    project_id = projects.json()["data"][0]["id"]
    engine_client.fail_next = True
    response = client.post(
        "/api/v1/tasks",
        headers=admin,
        json={
            "project_id": project_id,
            "scene_code": "flood",
            "task_type": "flood_pipeline",
            "title": "引擎不可用",
        },
    )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "engine_unavailable"
