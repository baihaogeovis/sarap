from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.models import (
    AlgoProfile,
    Area,
    Membership,
    Organization,
    Permission,
    Project,
    Role,
    RolePermission,
    Scene,
    SceneActivation,
    User,
)
from app.models.base import utcnow
from app.scenes.registry import DEMO_PILOT_CONFIG, FLOOD_MANIFEST
from app.services.permissions import PERMISSIONS, ROLE_PERMISSIONS

DEMO_USERS = (
    ("admin", "admin@sarap.local", "admin123", "系统管理员"),
    ("duty_officer", "duty@sarap.local", "duty123", "值班员"),
    ("readonly", "readonly@sarap.local", "readonly123", "只读用户"),
)


def seed_if_empty(db: Session) -> None:
    if db.query(Organization).first() is not None:
        _ensure_rbac(db)
        db.commit()
        return
    _ensure_rbac(db)
    org = Organization(code="demo-org", name="SARAP 演示单位", status="active")
    db.add(org)
    db.flush()
    project = Project(
        org_id=org.id,
        code="demo-pilot",
        name="演示项目",
        status="active",
        default_crs=DEMO_PILOT_CONFIG["analysis_crs"],
        bbox_json=DEMO_PILOT_CONFIG["aoi"],
    )
    db.add(project)
    db.flush()
    area = Area(
        org_id=org.id,
        project_id=project.id,
        code="demo-area",
        name="示例区域",
        status="active",
        is_pilot=True,
        timezone="Asia/Shanghai",
        aoi_geojson={
            "type": "Polygon",
            "coordinates": [[[116.2, 39.6], [116.8, 39.6], [116.8, 40.1], [116.2, 40.1], [116.2, 39.6]]],
        },
        bbox_json=DEMO_PILOT_CONFIG["aoi"],
        analysis_crs=DEMO_PILOT_CONFIG["analysis_crs"],
        exchange_crs="EPSG:4490",
        grid_res_m=10,
        grid_origin_x=0,
        grid_origin_y=0,
        config_json={
            "algo_profile_id": "s1_grd_flood_v1",
            "suggested_target_minutes": 240,
            "publish": {"auto_publish_flood_event": False},
            "grid": DEMO_PILOT_CONFIG["grid"],
            "s1": DEMO_PILOT_CONFIG["s1"],
            "overrides": DEMO_PILOT_CONFIG["overrides"],
        },
    )
    db.add(area)
    db.flush()
    scene = db.query(Scene).filter(Scene.code == "flood").one_or_none()
    if scene is None:
        scene = Scene(
            code="flood",
            name="洪水应急",
            description="Sentinel-1 IW GRD 洪水淹没范围与影响统计。第一版不提供水深。",
            version="1.0.0",
            status="registered",
            manifest_json=FLOOD_MANIFEST,
        )
        db.add(scene)
        db.flush()
    if db.query(AlgoProfile).filter(AlgoProfile.code == "s1_grd_flood_v1").one_or_none() is None:
        db.add(
            AlgoProfile(
                org_id=org.id,
                scene_id=scene.id,
                code="s1_grd_flood_v1",
                name="Sentinel-1 IW GRD 默认配置档",
                version="1.0.0",
                status="active",
                params_json={
                    "T_default": -18,
                    "T_clamp": [-23, -14],
                    "mmu_ha": 0.3,
                    "suggested_target_minutes": 240,
                },
            )
        )
    db.add(
        SceneActivation(
            org_id=org.id,
            project_id=project.id,
            scene_id=scene.id,
            status="enabled",
            config_json=DEMO_PILOT_CONFIG,
            activated_at=utcnow(),
        )
    )
    for role_code, email, password, name in DEMO_USERS:
        user = User(email=email, name=name, password_hash=hash_password(password), status="active")
        db.add(user)
        db.flush()
        db.add(
            Membership(
                org_id=org.id,
                user_id=user.id,
                scope_type="organization",
                scope_id=org.id,
                role_code=role_code,
            )
        )
        db.add(
            Membership(
                org_id=org.id,
                user_id=user.id,
                scope_type="project",
                scope_id=project.id,
                role_code=role_code,
            )
        )
    db.commit()


def _ensure_rbac(db: Session) -> None:
    existing_perms = {row.code: row for row in db.query(Permission).all()}
    for code, description in PERMISSIONS.items():
        if code not in existing_perms:
            perm = Permission(code=code, name=code, description=description)
            db.add(perm)
            db.flush()
            existing_perms[code] = perm
    existing_roles = {row.code: row for row in db.query(Role).all()}
    reserved = {"platform_admin", "org_admin", "project_admin", "qc_reviewer", "analyst"}
    for code, perm_codes in ROLE_PERMISSIONS.items():
        role = existing_roles.get(code)
        if role is None:
            role = Role(
                code=code,
                name=code,
                description="Reserved role" if code in reserved else "V1 surface role",
                reserved=(code in reserved),
            )
            db.add(role)
            db.flush()
            existing_roles[code] = role
        have = {
            row.permission_id
            for row in db.query(RolePermission).filter(RolePermission.role_id == role.id).all()
        }
        for perm_code in perm_codes:
            perm = existing_perms[perm_code]
            if perm.id not in have:
                db.add(RolePermission(role_id=role.id, permission_id=perm.id))
    if db.query(Scene).filter(Scene.code == "flood").one_or_none() is None:
        db.add(
            Scene(
                code="flood",
                name="洪水应急",
                description="Sentinel-1 IW GRD 洪水淹没范围与影响统计。第一版不提供水深。",
                version="1.0.0",
                status="registered",
                manifest_json=FLOOD_MANIFEST,
            )
        )
