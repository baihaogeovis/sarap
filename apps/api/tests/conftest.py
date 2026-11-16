from __future__ import annotations

import os
from collections.abc import Generator
from pathlib import Path

# Must be set before the app reads settings / creates the engine.
os.environ.setdefault("SARAP_SEED_ON_STARTUP", "false")
os.environ.setdefault("SARAP_SECRET_KEY", "test-secret-key-please-use-32b!")
os.environ.setdefault("SARAP_INTERNAL_TOKEN", "test-internal-token")
os.environ.setdefault("SARAP_ENGINE_TOKEN", "test-internal-token")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.db import get_db
from app.models import Area, Base, Organization, Project
from app.services.engine_client import RecordingEngineClient, set_engine_client
from app.services.seed import seed_if_empty


@pytest.fixture()
def engine(tmp_path: Path):
    url = f"sqlite:///{tmp_path}/sarap-test.db"
    eng = create_engine(url, future=True, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=eng)
    return eng


@pytest.fixture()
def db(engine) -> Generator[Session, None, None]:
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    session = SessionLocal()
    seed_if_empty(session)
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def engine_client() -> RecordingEngineClient:
    client = RecordingEngineClient()
    set_engine_client(client)
    yield client
    set_engine_client(None)


@pytest.fixture()
def client(engine, db, engine_client) -> Generator[TestClient, None, None]:
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)

    def _get_db() -> Generator[Session, None, None]:
        session = SessionLocal()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    from app.main import app

    app.dependency_overrides[get_db] = _get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def login(client: TestClient, email: str, password: str) -> str:
    resp = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]["tokens"]["access_token"]


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


auth_header = auth


def admin_headers(client: TestClient) -> dict[str, str]:
    return auth(login(client, "admin@sarap.local", "admin123"))


def duty_headers(client: TestClient) -> dict[str, str]:
    return auth(login(client, "duty@sarap.local", "duty123"))


def readonly_headers(client: TestClient) -> dict[str, str]:
    return auth(login(client, "readonly@sarap.local", "readonly123"))


def demo_ids(db: Session) -> tuple[Organization, Project, Area]:
    org = db.query(Organization).filter(Organization.code == "demo-org").one()
    project = db.query(Project).filter(Project.code == "demo-pilot").one()
    area = db.query(Area).filter(Area.code == "demo-area").one()
    return org, project, area
