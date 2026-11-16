"""Thin HTTP client for the internal engine control plane.

The engine package is developed in parallel. This client is the only coupling
from the platform API: submit / status / cancel / priority bump.
"""

from __future__ import annotations

from typing import Any, Protocol

import httpx

from app.core.config import settings
from app.core.responses import APIError


class EngineClient(Protocol):
    def submit_job(self, payload: dict[str, Any]) -> dict[str, Any]: ...
    def get_job(self, job_id: str) -> dict[str, Any]: ...
    def cancel_job(self, job_id: str) -> dict[str, Any]: ...
    def bump_priority(self, job_id: str, priority: str) -> dict[str, Any]: ...


class HttpEngineClient:
    def __init__(self, base_url: str | None = None, token: str | None = None, timeout: float = 10.0) -> None:
        self.base_url = (base_url or settings.engine_url).rstrip("/")
        self.token = token or settings.engine_token
        self.timeout = timeout

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}", "X-Internal-Token": self.token}

    def _request(self, method: str, path: str, json: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self.base_url:
            raise APIError(503, "engine_unavailable", "Engine URL is not configured")
        url = f"{self.base_url}{path}"
        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.request(method, url, json=json, headers=self._headers())
        except httpx.HTTPError as exc:
            raise APIError(503, "engine_unavailable", f"Engine is unreachable: {exc}") from exc
        if response.status_code >= 400:
            raise APIError(
                503,
                "engine_unavailable",
                f"Engine returned HTTP {response.status_code}: {response.text[:300]}",
            )
        return response.json()

    def submit_job(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/internal/engine/jobs", json=payload)

    def get_job(self, job_id: str) -> dict[str, Any]:
        return self._request("GET", f"/internal/engine/jobs/{job_id}")

    def cancel_job(self, job_id: str) -> dict[str, Any]:
        return self._request("POST", f"/internal/engine/jobs/{job_id}/cancel")

    def bump_priority(self, job_id: str, priority: str) -> dict[str, Any]:
        return self._request("POST", f"/internal/engine/jobs/{job_id}/priority", json={"priority": priority})


class RecordingEngineClient:
    """In-process stand-in used by unit tests. Does not invent products."""

    def __init__(self) -> None:
        self.jobs: dict[str, dict[str, Any]] = {}
        self.fail_next = False

    def submit_job(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self.fail_next:
            self.fail_next = False
            raise APIError(503, "engine_unavailable", "Engine is unreachable: simulated outage")
        job_id = f"job-{len(self.jobs) + 1}"
        record = {"job_id": job_id, "state": "accepted", "payload": payload}
        self.jobs[job_id] = record
        return record

    def get_job(self, job_id: str) -> dict[str, Any]:
        if job_id not in self.jobs:
            raise APIError(404, "not_found", "Engine job not found")
        return self.jobs[job_id]

    def cancel_job(self, job_id: str) -> dict[str, Any]:
        job = self.get_job(job_id)
        job["state"] = "cancelled"
        return job

    def bump_priority(self, job_id: str, priority: str) -> dict[str, Any]:
        job = self.get_job(job_id)
        job["priority"] = priority
        return job


_override: EngineClient | None = None


def set_engine_client(client: EngineClient | None) -> None:
    global _override
    _override = client


def get_engine_client() -> EngineClient:
    if _override is not None:
        return _override
    return HttpEngineClient()
