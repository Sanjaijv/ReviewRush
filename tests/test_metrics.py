from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.main import app
from app.observability.metrics import webhook_request_latency_seconds


def test_metrics_endpoint_returns_prometheus_text_format(client: TestClient) -> None:
    response = client.get("/metrics")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert b"reviewrush_celery_queue_depth" in response.content


def test_metrics_reflects_observed_webhook_latency(client: TestClient) -> None:
    webhook_request_latency_seconds.labels(event_type="push", status="accepted").observe(0.05)

    response = client.get("/metrics")

    assert b"reviewrush_webhook_request_latency_seconds" in response.content
    assert b'event_type="push"' in response.content


def test_metrics_endpoint_disabled_returns_404() -> None:
    app.dependency_overrides[get_settings] = lambda: Settings(metrics_enabled=False)
    try:
        with TestClient(app) as c:
            response = c.get("/metrics")
    finally:
        app.dependency_overrides.pop(get_settings, None)

    assert response.status_code == 404
