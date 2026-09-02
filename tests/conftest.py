import os

os.environ.setdefault(
    "DATABASE_URL", "postgresql+psycopg://reviewrush:reviewrush@localhost:5432/reviewrush_test"
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/1")

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)
