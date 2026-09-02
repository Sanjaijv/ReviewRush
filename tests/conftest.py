import os

os.environ.setdefault(
    "DATABASE_URL", "postgresql+psycopg://reviewrush:reviewrush@localhost:5432/reviewrush_test"
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/1")
os.environ.setdefault("GITHUB_WEBHOOK_SECRET", "test-webhook-secret")

import pytest
from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.main import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def db_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
