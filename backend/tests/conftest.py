import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ["APP_ENV"] = "test"
os.environ["MT5_MODE"] = "mock"
os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"
os.environ["APP_SECRET_KEY"] = "test-secret"
os.environ["DASHBOARD_USERNAME"] = "admin"
os.environ["DASHBOARD_PASSWORD"] = "test-password"
os.environ["AGENT_API_KEY"] = "test-agent-key"
os.environ["SAAS_API_KEY"] = "test-saas-key"

from app.core.config import get_settings

get_settings.cache_clear()

from app.database.session import Base, configure_engine, get_db
from app.database.init_db import create_schema

configure_engine(os.environ["DATABASE_URL"])
create_schema()

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.workers.collector_loop import start_collector


@pytest.fixture()
def db_session():
    from app.database.session import SessionLocal

    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setattr("app.main.start_collector", lambda: {"status": "SKIPPED"})
    application = create_app()
    with TestClient(application) as test_client:
        yield test_client


@pytest.fixture()
def auth_headers(client):
    response = client.post("/api/auth/login", json={"username": "admin", "password": "test-password"})
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}
