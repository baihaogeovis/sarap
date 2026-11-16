from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.deps import Principal
from app.models import Briefing, Dataset, Product, Project, Task, User
from app.schemas.common import BriefingOut, ProductOut, ProjectOut, TaskOut, UserOut
from app.services.baselines import dataset_imagery_fields
from app.services.product import to_meta_safe


def user_out(user: User, principal: Principal) -> UserOut:
    return UserOut(
        id=user.id,
        email=user.email,
        name=user.name,
        status=user.status,
        roles=principal.roles,
        permissions=sorted(principal.permissions),
        org_id=principal.org_id,
    )


def project_out(row: Project) -> ProjectOut:
    return ProjectOut.model_validate(row)


def _imagery_from_dataset(db: Session | None, imagery_dataset_id) -> tuple:
    if db is None or imagery_dataset_id is None:
        return None, None, ""
    return dataset_imagery_fields(db.get(Dataset, imagery_dataset_id))


def task_out(row: Task, db: Session | None = None) -> TaskOut:
    data = TaskOut.model_validate(row)
    ds_start, ds_end, ds_s1 = _imagery_from_dataset(db, (row.params_json or {}).get("imagery_dataset_id"))
    if data.acquisition_start is None:
        data.acquisition_start = ds_start
    if data.acquisition_end is None:
        data.acquisition_end = ds_end
    if not data.s1_product_id:
        data.s1_product_id = ds_s1 or ""
    return data


def product_out(row: Product, db: Session | None = None) -> ProductOut:
    data = ProductOut.model_validate(row)
    data.metadata_json = to_meta_safe(data.metadata_json)
    ds_start, ds_end, ds_s1 = _imagery_from_dataset(db, row.imagery_dataset_id)
    if data.acquisition_start is None:
        data.acquisition_start = ds_start
    if data.acquisition_end is None:
        data.acquisition_end = ds_end
    if not data.s1_product_id:
        data.s1_product_id = ds_s1 or ""
    return data


def briefing_out(row: Briefing) -> BriefingOut:
    return BriefingOut.model_validate(row)
