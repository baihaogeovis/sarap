"""内部 HTTP：前缀 /internal/engine。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request

from sarap_engine.api.schemas import JobSubmitRequest, PriorityRequest
from sarap_engine.api.service import EngineService

router = APIRouter(prefix="/internal/engine", tags=["engine"])


def get_service(request: Request) -> EngineService:
    return request.app.state.service


def _presented_token(x_internal_token: str | None, authorization: str | None) -> str:
    if x_internal_token:
        return x_internal_token
    if authorization and authorization.lower().startswith("bearer "):
        return authorization.split(" ", 1)[1].strip()
    return ""


def _check_token(
    request: Request,
    x_internal_token: str | None,
    authorization: str | None = None,
) -> None:
    expected = getattr(request.app.state, "internal_token", "") or ""
    if not expected:
        return
    if _presented_token(x_internal_token, authorization) != expected:
        raise HTTPException(status_code=401, detail="invalid internal token")


@router.get("/health")
def health(request: Request) -> dict[str, Any]:
    return get_service(request).health()


@router.post("/jobs")
def submit_job(
    body: JobSubmitRequest,
    request: Request,
    x_internal_token: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _check_token(request, x_internal_token, authorization)
    svc = get_service(request)
    try:
        data, reused = svc.submit(body.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if reused:
        # 幂等命中，返回已有任务
        return data
    return data


@router.get("/jobs/{job_id}")
def get_job(
    job_id: str,
    request: Request,
    x_internal_token: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _check_token(request, x_internal_token, authorization)
    data = get_service(request).get(job_id)
    if data is None:
        raise HTTPException(status_code=404, detail="job not found")
    return data


@router.post("/jobs/{job_id}/cancel")
def cancel_job(
    job_id: str,
    request: Request,
    x_internal_token: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _check_token(request, x_internal_token, authorization)
    svc = get_service(request)
    if svc.get(job_id) is None:
        raise HTTPException(status_code=404, detail="job not found")
    try:
        return svc.cancel(job_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/jobs/{job_id}/priority")
def set_priority(
    job_id: str,
    body: PriorityRequest,
    request: Request,
    x_internal_token: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _check_token(request, x_internal_token, authorization)
    svc = get_service(request)
    if svc.get(job_id) is None:
        raise HTTPException(status_code=404, detail="job not found")
    return svc.set_priority(job_id, body.priority)
