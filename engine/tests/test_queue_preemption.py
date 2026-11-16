
from __future__ import annotations

import json

from sarap_engine.constants import JobStatus, Priority
from sarap_engine.orchestration.models import JobRow, utcnow
from sarap_engine.orchestration.preemption import should_preempt
from sarap_engine.orchestration.queue import JobQueue
from sarap_engine.orchestration.store import JobStore
from sarap_engine.orchestration.worker import Worker
from sarap_engine.products.ingest import IngestClient


def _row(store: JobStore, *, job_id: str, priority: str, status: str = "queued") -> JobRow:
    now = utcnow()
    row = JobRow(
        id=job_id,
        status=JobStatus.ACCEPTED.value,
        priority=priority,
        execution_mode="mock",
        idempotency_key=job_id,
        scene_id="s",
        pilot_id="p",
        baseline_version_id="",
        algo_profile_id="s1_grd_flood_v1",
        param_hash="x",
        payload_json="{}",
        submitted_at=now,
        updated_at=now,
    )
    store.add(row)
    store.transition(job_id, JobStatus.QUEUED)
    if status != "queued":
        store.update(job_id, status=status)
    return store.get(job_id)


def test_emergency_jumps_ahead_of_normal(store):
    _row(store, job_id="n1", priority=Priority.NORMAL.value)
    _row(store, job_id="n2", priority=Priority.NORMAL.value)
    _row(store, job_id="e1", priority=Priority.EMERGENCY.value)
    q = JobQueue(store)
    assert q.peek_order()[0] == "e1"
    first = q.pop_next()
    assert first.id == "e1"


def test_should_preempt_only_at_boundaries():
    assert should_preempt("normal", "extracting", emergency_waiting=True, gpt_running=False)
    assert should_preempt("normal", "preparing", emergency_waiting=True, gpt_running=False)
    assert should_preempt("normal", "snap_running", emergency_waiting=True, gpt_running=False)
    assert not should_preempt("normal", "snap_running", emergency_waiting=True, gpt_running=True)
    assert not should_preempt("emergency", "extracting", emergency_waiting=True, gpt_running=False)
    assert not should_preempt("normal", "extracting", emergency_waiting=False, gpt_running=False)


def test_worker_preempts_normal_job_at_step_boundary(store, settings):
    # 用 step_hook 在 preparing 结束边界插入应急任务
    normal = JobRow(
        id="job-normal",
        status=JobStatus.ACCEPTED.value,
        priority=Priority.NORMAL.value,
        execution_mode="mock",
        idempotency_key="k-n",
        scene_id="scene-n",
        pilot_id="pilot_demo",
        baseline_version_id="",
        algo_profile_id="s1_grd_flood_v1",
        param_hash="h",
        payload_json=json.dumps({
            "scene": {"scene_id": "scene-n", "polarizations": ["VV", "VH"]},
            "pilot": {
                "pilot_id": "pilot_demo",
                "analysis_crs": "EPSG:4548",
                "grid": {"res_m": 10, "origin_x": 0, "origin_y": 0, "width": 80, "height": 80},
            },
        }),
        submitted_at=utcnow(),
        updated_at=utcnow(),
        work_dir=str(settings.resolved_work_dir() / "job-normal"),
    )
    store.add(normal)
    store.transition("job-normal", JobStatus.QUEUED)

    def hook(row, status):
        if status == JobStatus.PREPARING and not store.has_queued_emergency():
            em = JobRow(
                id="job-emg",
                status=JobStatus.ACCEPTED.value,
                priority=Priority.EMERGENCY.value,
                execution_mode="mock",
                idempotency_key="k-e",
                scene_id="scene-e",
                pilot_id="pilot_demo",
                baseline_version_id="",
                algo_profile_id="s1_grd_flood_v1",
                param_hash="h",
                payload_json=normal.payload_json,
                submitted_at=utcnow(),
                updated_at=utcnow(),
            )
            store.add(em)
            store.transition("job-emg", JobStatus.QUEUED)

    ingest = IngestClient("http://ingest.invalid/products", mode="mock")
    worker = Worker(store, settings, ingest_client=ingest, step_hook=hook)
    worker.execute("job-normal")
    n = store.get("job-normal")
    e = store.get("job-emg")
    assert n.status == JobStatus.QUEUED.value
    # 检查点应记录让出步骤
    assert "preparing" in (n.checkpoint_json or "")
    assert e is not None and e.status == JobStatus.QUEUED.value
    assert e.priority == Priority.EMERGENCY.value
