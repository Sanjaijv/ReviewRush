import uuid

import pytest
from sqlalchemy import text

from app.models import Installation, Repository, WebhookDelivery
from app.tasks.github_webhook import process_github_webhook


@pytest.fixture(autouse=True)
def _cleanup(db_session):
    yield
    db_session.execute(text("DELETE FROM repositories"))
    db_session.execute(text("DELETE FROM webhook_deliveries"))
    db_session.execute(text("DELETE FROM installations"))
    db_session.commit()


def _delivery_id() -> str:
    return str(uuid.uuid4())


def test_installation_created_upserts_installation(db_session) -> None:
    delivery_id = _delivery_id()
    db_session.add(WebhookDelivery(delivery_id=delivery_id, event_type="installation"))
    db_session.commit()

    payload = {
        "action": "created",
        "installation": {"id": 999, "account": {"login": "acme", "type": "Organization"}},
    }

    process_github_webhook.run(delivery_id=delivery_id, event_type="installation", payload=payload)

    installation = db_session.query(Installation).filter_by(github_installation_id=999).one()
    assert installation.account_login == "acme"
    assert installation.status == "active"

    delivery = db_session.query(WebhookDelivery).filter_by(delivery_id=delivery_id).one()
    assert delivery.status == "processed"


def test_installation_deleted_deactivates_repositories(db_session) -> None:
    installation = Installation(
        github_installation_id=1000, account_login="acme", account_type="Organization"
    )
    db_session.add(installation)
    db_session.flush()
    repo = Repository(
        installation_id=installation.id,
        github_repo_id=555,
        owner="acme",
        name="widgets",
        full_name="acme/widgets",
        is_active=True,
    )
    db_session.add(repo)
    db_session.commit()

    delivery_id = _delivery_id()
    db_session.add(WebhookDelivery(delivery_id=delivery_id, event_type="installation"))
    db_session.commit()

    payload = {"action": "deleted", "installation": {"id": 1000, "account": {}}}
    process_github_webhook.run(delivery_id=delivery_id, event_type="installation", payload=payload)

    db_session.refresh(installation)
    db_session.refresh(repo)
    assert installation.status == "deleted"
    assert repo.is_active is False


def test_installation_repositories_added_creates_repository(db_session) -> None:
    installation = Installation(
        github_installation_id=2000, account_login="acme", account_type="Organization"
    )
    db_session.add(installation)
    db_session.commit()

    delivery_id = _delivery_id()
    db_session.add(WebhookDelivery(delivery_id=delivery_id, event_type="installation_repositories"))
    db_session.commit()

    payload = {
        "action": "added",
        "installation": {"id": 2000},
        "repositories_added": [{"id": 777, "full_name": "acme/gizmos"}],
        "repositories_removed": [],
    }
    process_github_webhook.run(
        delivery_id=delivery_id, event_type="installation_repositories", payload=payload
    )

    repository = db_session.query(Repository).filter_by(github_repo_id=777).one()
    assert repository.full_name == "acme/gizmos"
    assert repository.is_active is True


def test_installation_repositories_removed_deactivates_repository(db_session) -> None:
    installation = Installation(
        github_installation_id=3000, account_login="acme", account_type="Organization"
    )
    db_session.add(installation)
    db_session.flush()
    repo = Repository(
        installation_id=installation.id,
        github_repo_id=888,
        owner="acme",
        name="sprockets",
        full_name="acme/sprockets",
        is_active=True,
    )
    db_session.add(repo)
    db_session.commit()

    delivery_id = _delivery_id()
    db_session.add(WebhookDelivery(delivery_id=delivery_id, event_type="installation_repositories"))
    db_session.commit()

    payload = {
        "action": "removed",
        "installation": {"id": 3000},
        "repositories_added": [],
        "repositories_removed": [{"id": 888, "full_name": "acme/sprockets"}],
    }
    process_github_webhook.run(
        delivery_id=delivery_id, event_type="installation_repositories", payload=payload
    )

    db_session.refresh(repo)
    assert repo.is_active is False


def test_unhandled_event_type_is_marked_processed(db_session) -> None:
    delivery_id = _delivery_id()
    db_session.add(WebhookDelivery(delivery_id=delivery_id, event_type="push"))
    db_session.commit()

    process_github_webhook.run(delivery_id=delivery_id, event_type="push", payload={})

    delivery = db_session.query(WebhookDelivery).filter_by(delivery_id=delivery_id).one()
    assert delivery.status == "processed"
