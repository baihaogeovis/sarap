
from __future__ import annotations

import pytest

from sarap_engine.constants import JobStatus
from sarap_engine.orchestration.state_machine import (
    IllegalTransition,
    can_transition,
    is_terminal,
    transition,
)


def test_happy_path_transitions():
    path = [
        JobStatus.ACCEPTED,
        JobStatus.QUEUED,
        JobStatus.PREPARING,
        JobStatus.SNAP_RUNNING,
        JobStatus.EXTRACTING,
        JobStatus.CHANGE_DETECTING,
        JobStatus.IMPACT_MAPPING,
        JobStatus.QC,
        JobStatus.INGESTING,
        JobStatus.SUCCEEDED,
    ]
    for a, b in zip(path, path[1:]):
        assert can_transition(a, b)
        assert transition(a, b) == b


@pytest.mark.parametrize(
    "src,dst",
    [
        (JobStatus.SUCCEEDED, JobStatus.QUEUED),
        (JobStatus.FAILED, JobStatus.SUCCEEDED),
        (JobStatus.CANCELLED, JobStatus.QUEUED),
        (JobStatus.QUEUED, JobStatus.SUCCEEDED),
        (JobStatus.ACCEPTED, JobStatus.SNAP_RUNNING),
        (JobStatus.SNAP_RUNNING, JobStatus.PREEMPTED),  # 不允许在 gpt 运行中直接 preempted
        (JobStatus.INGESTING, JobStatus.EXTRACTING),
    ],
)
def test_illegal_transitions(src, dst):
    assert not can_transition(src, dst)
    with pytest.raises(IllegalTransition):
        transition(src, dst)


def test_preempted_returns_to_queued():
    assert transition(JobStatus.EXTRACTING, JobStatus.PREEMPTED) == JobStatus.PREEMPTED
    assert transition(JobStatus.PREEMPTED, JobStatus.QUEUED) == JobStatus.QUEUED


def test_retry_wait_and_terminal():
    assert transition(JobStatus.SNAP_RUNNING, JobStatus.RETRY_WAIT) == JobStatus.RETRY_WAIT
    assert transition(JobStatus.RETRY_WAIT, JobStatus.QUEUED) == JobStatus.QUEUED
    assert is_terminal(JobStatus.SUCCEEDED)
    assert is_terminal("failed")
    assert not is_terminal(JobStatus.QUEUED)
