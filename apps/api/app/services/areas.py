from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.core.responses import APIError
from app.models import DataAsset, DataAssetVersion


def has_published_permanent_water(
    db: Session,
    org_id: uuid.UUID,
    *,
    project_id: uuid.UUID | None = None,
    area_id: uuid.UUID | None = None,
) -> bool:
    q = (
        db.query(DataAssetVersion)
        .join(DataAsset, DataAsset.id == DataAssetVersion.asset_id)
        .filter(
            DataAsset.org_id == org_id,
            DataAsset.asset_type == "permanent_water",
            DataAsset.status == "active",
            DataAsset.deleted_at.is_(None),
            DataAssetVersion.review_status == "published",
            DataAssetVersion.deleted_at.is_(None),
        )
    )
    if area_id is not None:
        q = q.filter((DataAsset.area_id == area_id) | (DataAsset.area_id.is_(None)))
    if project_id is not None:
        q = q.filter((DataAsset.project_id == project_id) | (DataAsset.project_id.is_(None)))
    return q.first() is not None


def auto_publish_flood_event_requested(config: dict[str, Any] | None) -> bool:
    publish = (config or {}).get("publish") or {}
    if publish.get("auto_publish_flood_event") is True:
        return True
    # Do not treat auto_publish_if_qc_pass as flood-event auto publish.
    return False


def validate_area_config(
    db: Session,
    org_id: uuid.UUID,
    config: dict[str, Any] | None,
    *,
    project_id: uuid.UUID | None = None,
    area_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    """Return a normalized config. Block auto flood-event publish without a published baseline.

    Quasi-extent tasks and P0 short publish are never blocked here.
    """
    cfg = dict(config or {})
    # Normalize SLA naming: suggested target, not a contractual SLA.
    if "sla_minutes" in cfg and "suggested_target_minutes" not in cfg:
        cfg["suggested_target_minutes"] = cfg.pop("sla_minutes")
    else:
        cfg.pop("sla_minutes", None)
    publish = dict(cfg.get("publish") or {})
    if "sla_minutes" in publish and "suggested_target_minutes" not in publish:
        publish["suggested_target_minutes"] = publish.pop("sla_minutes")
    else:
        publish.pop("sla_minutes", None)
    cfg["publish"] = publish
    if auto_publish_flood_event_requested(cfg) and not has_published_permanent_water(
        db, org_id, project_id=project_id, area_id=area_id
    ):
        raise APIError(
            400,
            "baseline_required",
            "缺已发布常年水体本底时不允许启用自动本次淹没发布；准范围任务与最短发布不受影响",
        )
    return cfg


def baseline_warning(
    db: Session,
    org_id: uuid.UUID,
    *,
    project_id: uuid.UUID | None = None,
    area_id: uuid.UUID | None = None,
) -> dict[str, str] | None:
    if has_published_permanent_water(db, org_id, project_id=project_id, area_id=area_id):
        return None
    return {
        "code": "baseline_missing",
        "message": "未配置已发布常年水体本底。P0 仍可开通场景并发布准范围；面积将标记为「提取水体面积（未扣本底）」，不可自动发布本次淹没。",
    }
