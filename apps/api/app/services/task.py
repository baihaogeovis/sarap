from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.deps import Principal
from app.core.responses import APIError
from app.models import Area, DataAssetVersion, Dataset, ProcessingJob, Scene, SceneActivation, Task
from app.models.base import utcnow
from app.services import audit
from app.services.engine_client import get_engine_client

HARD_ERROR_CODES = {"PROCESSING_FAILED", "GRID_MISALIGNED", "COVERAGE_TOO_LOW"}


def require_scene_enabled(db: Session, project_id: uuid.UUID, scene_code: str) -> tuple[Scene, SceneActivation]:
    scene = db.query(Scene).filter(Scene.code == scene_code, Scene.deleted_at.is_(None)).one_or_none()
    if scene is None:
        raise APIError(404, "not_found", f"Scene '{scene_code}' is not registered")
    activation = (
        db.query(SceneActivation)
        .filter(SceneActivation.project_id == project_id, SceneActivation.scene_id == scene.id)
        .one_or_none()
    )
    if activation is None or activation.status != "enabled":
        raise APIError(409, "scene_not_activated", f"Scene '{scene_code}' is not enabled on this project")
    return scene, activation



def _iso_utc(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _aoi_wkt(geojson: dict | None) -> str | None:
    """Turn an area GeoJSON geometry into WKT for the engine AOI. Invalid shapes are skipped."""
    if not geojson or not isinstance(geojson, dict):
        return None
    geometry = geojson.get("geometry") if geojson.get("type") == "Feature" else geojson
    if not isinstance(geometry, dict):
        return None
    try:
        from shapely.geometry import shape

        geom = shape(geometry)
    except (TypeError, ValueError, AttributeError, KeyError):
        return None
    if geom is None or geom.is_empty:
        return None
    return geom.wkt


def build_engine_payload(db: Session, task: Task) -> dict:
    """Platform -> engine job body.

    scene_id / scene_code are the platform scene (e.g. flood), never a Sentinel-1 PRODUCT-ID.
    Area is identified by area_id; is_pilot is only a config flag. pilot_id is not required
    and is not a unique spatial key.
    """
    params = dict(task.params_json or {})
    payload: dict = {
        "task_id": str(task.id),
        "org_id": str(task.org_id),
        "project_id": str(task.project_id),
        "scene_code": task.scene_code,
        "task_type": task.task_type,
        "priority": "emergency" if task.emergency else task.priority,
        "params": params,
    }
    if task.scene_id is not None:
        payload["scene_id"] = str(task.scene_id)
    if task.area_id is not None:
        payload["area_id"] = str(task.area_id)
        area = db.get(Area, task.area_id)
        if area is not None and area.is_pilot:
            payload["is_pilot"] = True
            params.setdefault("is_pilot", True)
    if task.s1_product_id:
        payload["s1_product_id"] = task.s1_product_id
    start = _iso_utc(task.acquisition_start)
    end = _iso_utc(task.acquisition_end)
    if start:
        payload["acquisition_start"] = start
    if end:
        payload["acquisition_end"] = end
    if task.baseline_version_id is not None:
        payload["baseline_version_id"] = str(task.baseline_version_id)
    if task.algo_profile_id:
        payload["algo_profile_id"] = task.algo_profile_id
    area = db.get(Area, task.area_id) if task.area_id is not None else None
    if area is not None:
        pilot: dict = {
            "area_id": str(area.id),
            "name": area.name,
            "is_pilot": bool(area.is_pilot),
            "timezone": area.timezone or "Asia/Shanghai",
            "analysis_crs": area.analysis_crs,
            "exchange_crs": area.exchange_crs,
            "aoi_crs": area.exchange_crs,
            "grid": {
                "res_m": area.grid_res_m,
                "origin_x": area.grid_origin_x,
                "origin_y": area.grid_origin_y,
            },
        }
        wkt = _aoi_wkt(area.aoi_geojson)
        if wkt:
            pilot["aoi_wkt"] = wkt
        config = area.config_json if isinstance(area.config_json, dict) else {}
        if config.get("algo_profile_id") and not payload.get("algo_profile_id"):
            payload["algo_profile_id"] = config["algo_profile_id"]
            pilot["algo_profile_id"] = config["algo_profile_id"]
        elif payload.get("algo_profile_id"):
            pilot["algo_profile_id"] = payload["algo_profile_id"]
        if isinstance(config.get("overrides"), dict):
            pilot["overrides"] = config["overrides"]
        if config.get("suggested_target_minutes"):
            pilot["suggested_target_minutes"] = config["suggested_target_minutes"]
        payload["pilot"] = pilot
        # Keep the flat params the engine also reads, using this area's CRS — not a fixed basin.
        params.setdefault("analysis_crs", area.analysis_crs)
        params.setdefault("area_name", area.name)
        if wkt:
            params.setdefault("aoi_wkt", wkt)
    dataset = None
    imagery_id = params.get("imagery_dataset_id")
    if imagery_id:
        try:
            dataset_id = imagery_id if isinstance(imagery_id, uuid.UUID) else uuid.UUID(str(imagery_id))
        except (TypeError, ValueError, AttributeError):
            dataset_id = None
        if dataset_id is not None:
            dataset = db.get(Dataset, dataset_id)
    scene: dict = {}
    if dataset is not None and dataset.storage_uri:
        scene["input_uri"] = dataset.storage_uri
    if scene:
        payload["scene"] = scene
    if task.baseline_version_id is not None:
        version = db.get(DataAssetVersion, task.baseline_version_id)
        if version is not None and (version.storage_uri or "").strip():
            payload["baseline_uri"] = version.storage_uri
    if task.data_ready_at is not None:
        ready = _iso_utc(task.data_ready_at)
        if ready:
            payload["data_ready_at"] = ready
    return payload


def dispatch(db: Session, task: Task, principal: Principal) -> Task:
    client = get_engine_client()
    payload = build_engine_payload(db, task)
    try:
        result = client.submit_job(payload)
    except APIError as exc:
        task.status = "failed"
        task.error_message = exc.message
        task.finished_at = utcnow()
        db.add(task)
        audit.record(
            db,
            actor_type=principal.typ,
            actor_id=principal.id,
            action="task.dispatch_failed",
            resource_type="task",
            resource_id=str(task.id),
            org_id=task.org_id,
            project_id=task.project_id,
            after={"error": exc.message},
        )
        db.flush()
        raise
    task.engine_job_id = str(result.get("job_id") or result.get("id") or "")
    task.status = "queued"
    task.step = str(result.get("state") or "accepted")
    if task.submitted_at is None:
        task.submitted_at = utcnow()
    db.add(
        ProcessingJob(
            org_id=task.org_id,
            task_id=task.id,
            engine_job_id=task.engine_job_id,
            status=str(result.get("state") or "accepted"),
        )
    )
    db.add(task)
    audit.record(
        db,
        actor_type=principal.typ,
        actor_id=principal.id,
        action="task.dispatch",
        resource_type="task",
        resource_id=str(task.id),
        org_id=task.org_id,
        project_id=task.project_id,
        after={"engine_job_id": task.engine_job_id},
    )
    db.flush()
    return task


def cancel(db: Session, task: Task, principal: Principal) -> Task:
    principal.require("task.cancel")
    if task.status in {"succeeded", "cancelled"}:
        raise APIError(409, "invalid_transition", f"Cannot cancel a task in status {task.status}")
    if task.engine_job_id:
        try:
            get_engine_client().cancel_job(task.engine_job_id)
        except APIError as exc:
            if exc.code != "engine_unavailable":
                raise
            # Still mark cancelled locally if the engine is gone; record the warning.
            task.error_message = f"Cancel requested; engine unreachable: {exc.message}"
    task.status = "cancelled"
    task.finished_at = utcnow()
    db.add(task)
    audit.record(
        db,
        actor_type=principal.typ,
        actor_id=principal.id,
        action="task.cancel",
        resource_type="task",
        resource_id=str(task.id),
        org_id=task.org_id,
        project_id=task.project_id,
    )
    db.flush()
    return task


def retry(db: Session, task: Task, principal: Principal) -> Task:
    principal.require("task.retry")
    if task.status not in {"failed", "cancelled"}:
        raise APIError(409, "invalid_transition", "Only failed or cancelled tasks can be retried")
    task.status = "queued"
    task.progress = 0
    task.step = ""
    task.error_message = ""
    task.engine_job_id = ""
    task.finished_at = None
    task.started_at = None
    db.add(task)
    db.flush()
    return dispatch(db, task, principal)


def find_by_idempotency(db: Session, org_id, key: str | None) -> Task | None:
    if not key:
        return None
    return (
        db.query(Task)
        .filter(Task.org_id == org_id, Task.idempotency_key == key, Task.deleted_at.is_(None))
        .one_or_none()
    )


def apply_event(db: Session, task: Task, payload: dict) -> Task:
    """Engine / service callback: update status, progress, and UTC time fields."""
    if "progress" in payload:
        task.progress = int(payload["progress"])
    if "progress_json" in payload and isinstance(payload["progress_json"], dict):
        task.progress_json = payload["progress_json"]
    if "step" in payload:
        task.step = str(payload["step"])
    if payload.get("log_uri"):
        task.log_uri = str(payload["log_uri"])
    if payload.get("error_code"):
        task.error_code = str(payload["error_code"])
    if payload.get("error_message"):
        task.error_message = str(payload["error_message"])
    if payload.get("data_ready_at"):
        task.data_ready_at = payload["data_ready_at"]
    if payload.get("processed_at"):
        task.processed_at = payload["processed_at"]
    if "status" in payload and payload["status"] in {"queued", "running", "succeeded", "failed", "cancelled"}:
        task.status = payload["status"]
    if task.error_code in HARD_ERROR_CODES and task.status not in {"failed", "cancelled"}:
        task.status = "failed"
    if task.status == "running" and task.started_at is None:
        task.started_at = utcnow()
    if task.status in {"succeeded", "failed", "cancelled"}:
        task.finished_at = utcnow()
        if task.status == "succeeded" and task.processed_at is None:
            task.processed_at = task.finished_at
    job = (
        db.query(ProcessingJob)
        .filter(ProcessingJob.task_id == task.id)
        .order_by(ProcessingJob.created_at.desc())
        .first()
    )
    if job is not None:
        job.status = task.status
        job.step = task.step
        job.error_code = task.error_code
        job.log_uri = task.log_uri
        if payload.get("progress_json"):
            job.progress_json = payload["progress_json"]
        if task.started_at:
            job.started_at = task.started_at
        if task.finished_at:
            job.finished_at = task.finished_at
    db.add(task)
    db.flush()
    return task


def get_area(db: Session, area_id, org_id) -> Area:
    area = db.get(Area, area_id)
    if area is None or area.org_id != org_id or area.deleted_at is not None:
        raise APIError(404, "not_found", "Area not found")
    return area
