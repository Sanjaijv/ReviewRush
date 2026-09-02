from unittest.mock import patch

from fastapi.testclient import TestClient


def test_live_always_ok(client: TestClient) -> None:
    response = client.get("/api/v1/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ready_ok_when_dependencies_available(client: TestClient) -> None:
    with (
        patch("app.api.v1.health.database_is_ready", return_value=True),
        patch("app.api.v1.health.redis_is_ready", return_value=True),
    ):
        response = client.get("/api/v1/health/ready")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_ready_fails_when_database_unavailable(client: TestClient) -> None:
    with (
        patch("app.api.v1.health.database_is_ready", return_value=False),
        patch("app.api.v1.health.redis_is_ready", return_value=True),
    ):
        response = client.get("/api/v1/health/ready")
    assert response.status_code == 503
    assert response.json()["checks"]["database"] is False


def test_ready_fails_when_redis_unavailable(client: TestClient) -> None:
    with (
        patch("app.api.v1.health.database_is_ready", return_value=True),
        patch("app.api.v1.health.redis_is_ready", return_value=False),
    ):
        response = client.get("/api/v1/health/ready")
    assert response.status_code == 503
    assert response.json()["checks"]["redis"] is False
