from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.models import AuditLog


def record(
    db: Session,
    *,
    actor_type: str,
    actor_id: uuid.UUID | None,
    action: str,
    resource_type: str,
    resource_id: str,
    org_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    request_id: str = "",
) -> AuditLog:
    row = AuditLog(
        org_id=org_id,
        project_id=project_id,
        actor_type=actor_type,
        actor_id=actor_id,
        action=action,
        resource_type=resource_type,
        resource_id=str(resource_id),
        request_id=request_id,
        before_json=before,
        after_json=after,
    )
    db.add(row)
    return row
