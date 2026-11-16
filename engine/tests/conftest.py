
from __future__ import annotations

import pytest

from sarap_engine.config import Settings
from sarap_engine.orchestration.store import JobStore
from sarap_engine.orchestration.worker import Worker
from sarap_engine.products.ingest import IngestClient


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        mode="mock",
        work_dir=tmp_path / "work",
        db_url="sqlite:///:memory:",
        ingest_mode="mock",
        run_inline=False,
    )


@pytest.fixture
def store() -> JobStore:
    return JobStore("sqlite:///:memory:")


@pytest.fixture
def worker(store, settings) -> Worker:
    ingest = IngestClient("http://ingest.invalid/products", mode="mock")
    return Worker(store, settings, ingest_client=ingest)
