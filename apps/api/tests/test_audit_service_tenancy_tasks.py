from __future__ import annotations

from sqlalchemy import delete, update
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.models import AuditLog, AuditLogImmutableError, Membership, Organization, User
from app.services import audit
from tests.conftest import admin_headers, auth, demo_ids, duty_headers, login, readonly_headers


def test_audit_log_is_immutable(db: Session):
    row = audit.record(
        db,
        actor_type="user",
        actor_id=None,
        action="test.write",
        resource_type="probe",
        resource_id="1",
        org_id=None,
        after={"ok": True},
    )
    db.commit()
    db.refresh(row)
    row.action = "mutated"
    try:
        db.commit()
        raise AssertionError("update should have failed")
    except AuditLogImmutableError:
        db.rollback()
    try:
        db.execute(update(AuditLog).where(AuditLog.id == row.id).values(action="bulk"))
        db.commit()
        raise AssertionError("bulk update should have failed")
    except AuditLogImmutableError:
        db.rollback()
    try:
        db.execute(delete(AuditLog).where(AuditLog.id == row.id))
        db.commit()
        raise AssertionError("delete should have failed")
    except AuditLogImmutableError:
        db.rollback()
    assert db.get(AuditLog, row.id) is not None


def test_service_account_api_key_and_no_password_login(client, db):
    admin = admin_headers(client)
    created = client.post(
        "/api/v1/service-accounts",
        json={"name": "engine-ingest", "scopes": ["api.invoke"]},
        headers=admin,
    )
    assert created.status_code == 201, created.text
    data = created.json()["data"]
    api_key = data["api_key"]
    assert api_key
    # plaintext is not listed later
    listed = client.get("/api/v1/service-accounts", headers=admin)
    assert all(item.get("api_key") is None for item in listed.json()["data"])

    # cannot password-login as the service client_id
    denied = client.post("/api/v1/auth/login", json={"email": data["client_id"], "password": api_key})
    assert denied.status_code == 401

    _, project, area = demo_ids(db)
    # create a task as duty, then callback with API key
    duty = duty_headers(client)
    task = client.post(
        "/api/v1/tasks",
        json={
            "project_id": str(project.id),
            "area_id": str(area.id),
            "scene_code": "flood",
            "task_type": "water_extract",
            "title": "准范围任务",
            "data_ready_at": "2026-11-14T01:00:00Z",
        },
        headers=duty,
    )
    assert task.status_code == 201, task.text
    task_id = task.json()["data"]["id"]
    assert task.json()["data"]["submitted_at"]

    ev = client.post(
        f"/api/v1/internal/tasks/{task_id}/events",
        json={"status": "running", "progress": 40, "step": "snap_running"},
        headers={"X-API-Key": api_key},
    )
    assert ev.status_code == 200, ev.text
    assert ev.json()["data"]["status"] == "running"

    ingest = client.post(
        "/api/v1/internal/products",
        json={
            "task_id": task_id,
            "product_type": "SARAP_FLOOD_V1",
            "title": "引擎回传",
            "extracted_water_ha": 8.5,
            "artifacts_json": [{"layer_key": "class_map", "storage_uri": "file://cm.tif"}],
        },
        headers={"X-API-Key": api_key},
    )
    assert ingest.status_code == 201, ingest.text
    body = ingest.json()["data"]
    assert body["status"] == "draft"
    assert body["org_id"]
    assert body["flood_event_status"] == "baseline_missing"
    assert body["extracted_water_ha"] == 8.5
    assert body["processed_at"]


def test_org_isolation(client, db):
    # Second org + admin, hidden from demo-org users.
    other = Organization(code="other-org", name="另一单位", status="active")
    db.add(other)
    db.flush()
    user = User(
        email="other@example.com",
        name="其他管理员",
        password_hash=hash_password("other123"),
        status="active",
    )
    db.add(user)
    db.flush()
    db.add(
        Membership(
            org_id=other.id,
            user_id=user.id,
            scope_type="organization",
            scope_id=other.id,
            role_code="admin",
        )
    )
    db.commit()

    duty = duty_headers(client)
    _, project, area = demo_ids(db)
    product = client.post(
        "/api/v1/products",
        json={
            "project_id": str(project.id),
            "area_id": str(area.id),
            "product_type": "SARAP_FLOOD_V1",
            "title": "A 户产品",
            "extracted_water_ha": 1.0,
        },
        headers=duty,
    ).json()["data"]
    assert product["org_id"] == str(demo_ids(db)[0].id)

    other_token = login(client, "other@example.com", "other123")
    hidden = client.get(f"/api/v1/products/{product['id']}", headers=auth(other_token))
    assert hidden.status_code == 404
    listed = client.get("/api/v1/products", headers=auth(other_token))
    assert listed.status_code == 200
    assert listed.json()["data"] == []


def test_task_idempotency(client, db):
    duty = duty_headers(client)
    _, project, area = demo_ids(db)
    payload = {
        "project_id": str(project.id),
        "area_id": str(area.id),
        "scene_code": "flood",
        "task_type": "water_extract",
        "title": "幂等任务",
        "idempotency_key": "scene-flood-area-demo-v1",
        "data_ready_at": "2026-11-14T00:00:00Z",
    }
    first = client.post("/api/v1/tasks", json=payload, headers=duty)
    assert first.status_code == 201, first.text
    first_id = first.json()["data"]["id"]
    again = client.post("/api/v1/tasks", json=payload, headers=duty)
    assert again.status_code == 200, again.text
    assert again.json()["data"]["id"] == first_id
    assert again.json()["meta"].get("idempotent") is True

    rerun = client.post("/api/v1/tasks", json={**payload, "force_rerun": True}, headers=duty)
    assert rerun.status_code == 201, rerun.text
    assert rerun.json()["data"]["id"] != first_id


def test_activate_scene_without_baseline_warns(client, db):
    admin = admin_headers(client)
    # new project, activate flood with no baseline — warning, not 400/403
    created = client.post(
        "/api/v1/projects",
        json={"code": "p-no-base", "name": "无本底项目", "default_crs": "EPSG:4548"},
        headers=admin,
    )
    assert created.status_code == 201, created.text
    pid = created.json()["data"]["id"]
    act = client.post(
        f"/api/v1/projects/{pid}/scenes",
        json={"scene_code": "flood", "config_json": {"suggested_target_minutes": 240}},
        headers=admin,
    )
    assert act.status_code == 200, act.text
    warnings = act.json()["meta"].get("warnings") or []
    assert any(w["code"] == "baseline_missing" for w in warnings)

    # auto flood-event publish is blocked
    area = client.post(
        f"/api/v1/projects/{pid}/areas",
        json={
            "code": "area-x",
            "name": "可配置区域",
            "is_pilot": True,
            "analysis_crs": "EPSG:4548",
            "config_json": {"publish": {"auto_publish_flood_event": True}},
        },
        headers=admin,
    )
    assert area.status_code == 400, area.text

    # area without that flag is fine, still warned
    area2 = client.post(
        f"/api/v1/projects/{pid}/areas",
        json={
            "code": "area-y",
            "name": "可配置区域乙",
            "is_pilot": True,
            "analysis_crs": "EPSG:4548",
            "config_json": {"suggested_target_minutes": 240},
        },
        headers=admin,
    )
    assert area2.status_code == 201, area2.text
    assert any(w["code"] == "baseline_missing" for w in (area2.json()["meta"].get("warnings") or []))


def test_v1_cannot_bind_reserved_roles(client, db):
    admin = admin_headers(client)
    _, project, _ = demo_ids(db)
    # pick the readonly user and try to bind qc_reviewer
    me = client.get("/api/v1/auth/me", headers=readonly_headers(client)).json()["data"]
    resp = client.post(
        f"/api/v1/projects/{project.id}/members",
        json={"user_id": me["id"], "role_code": "qc_reviewer"},
        headers=admin,
    )
    assert resp.status_code == 403


def test_readonly_cannot_publish(client, db):
    duty = duty_headers(client)
    ro = readonly_headers(client)
    from tests.test_rbac_products import _draft

    product = _draft(client, db, duty, title="只读不可发")
    resp = client.post(f"/api/v1/products/{product['id']}/publish", json={}, headers=ro)
    assert resp.status_code == 403
