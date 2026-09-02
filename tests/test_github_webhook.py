import hashlib
import hmac
import json
import uuid
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.config import get_settings
from app.models import WebhookDelivery

SECRET = get_settings().github_webhook_secret


def _sign(body: bytes) -> str:
    return "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()


def _payload(action: str = "created") -> dict:
    return {"action": action, "installation": {"id": 12345}}


@pytest.fixture(autouse=True)
def _cleanup_deliveries(db_session):
    yield
    db_session.execute(text("DELETE FROM webhook_deliveries"))
    db_session.commit()


def test_valid_signed_webhook_is_accepted_and_queued(client: TestClient, db_session) -> None:
    body = json.dumps(_payload()).encode()
    delivery_id = str(uuid.uuid4())

    with patch("app.api.v1.github_webhook.process_github_webhook") as mock_task:
        response = client.post(
            "/api/v1/github/webhook",
            content=body,
            headers={
                "X-Hub-Signature-256": _sign(body),
                "X-GitHub-Delivery": delivery_id,
                "X-GitHub-Event": "installation",
                "Content-Type": "application/json",
            },
        )

    assert response.status_code == 202
    mock_task.delay.assert_called_once()

    stored = db_session.query(WebhookDelivery).filter_by(delivery_id=delivery_id).one()
    assert stored.event_type == "installation"
    assert stored.github_installation_id == 12345


def test_invalid_signature_is_rejected(client: TestClient, db_session) -> None:
    body = json.dumps(_payload()).encode()
    delivery_id = str(uuid.uuid4())

    with patch("app.api.v1.github_webhook.process_github_webhook") as mock_task:
        response = client.post(
            "/api/v1/github/webhook",
            content=body,
            headers={
                "X-Hub-Signature-256": "sha256=" + "0" * 64,
                "X-GitHub-Delivery": delivery_id,
                "X-GitHub-Event": "installation",
                "Content-Type": "application/json",
            },
        )

    assert response.status_code == 401
    mock_task.delay.assert_not_called()
    assert (
        db_session.query(WebhookDelivery).filter_by(delivery_id=delivery_id).one_or_none() is None
    )


def test_missing_signature_is_rejected(client: TestClient) -> None:
    body = json.dumps(_payload()).encode()

    with patch("app.api.v1.github_webhook.process_github_webhook") as mock_task:
        response = client.post(
            "/api/v1/github/webhook",
            content=body,
            headers={
                "X-GitHub-Delivery": str(uuid.uuid4()),
                "X-GitHub-Event": "installation",
                "Content-Type": "application/json",
            },
        )

    assert response.status_code == 401
    mock_task.delay.assert_not_called()


def test_replayed_delivery_id_is_not_processed_twice(client: TestClient, db_session) -> None:
    body = json.dumps(_payload()).encode()
    delivery_id = str(uuid.uuid4())
    headers = {
        "X-Hub-Signature-256": _sign(body),
        "X-GitHub-Delivery": delivery_id,
        "X-GitHub-Event": "installation",
        "Content-Type": "application/json",
    }

    with patch("app.api.v1.github_webhook.process_github_webhook") as mock_task:
        first = client.post("/api/v1/github/webhook", content=body, headers=headers)
        second = client.post("/api/v1/github/webhook", content=body, headers=headers)

    assert first.status_code == 202
    assert second.status_code == 200
    assert second.json()["status"] == "duplicate ignored"
    mock_task.delay.assert_called_once()

    count = db_session.query(WebhookDelivery).filter_by(delivery_id=delivery_id).count()
    assert count == 1
