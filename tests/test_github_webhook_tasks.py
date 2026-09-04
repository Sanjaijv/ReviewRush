import uuid
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import text

from app.models import Installation, RepoFileIndex, Repository, RepoSymbolChunk, WebhookDelivery
from app.tasks.github_webhook import process_github_webhook


@pytest.fixture(autouse=True)
def _cleanup(db_session):
    yield
    db_session.execute(text("DELETE FROM repo_symbol_chunks"))
    db_session.execute(text("DELETE FROM repo_file_index"))
    db_session.execute(text("DELETE FROM repositories"))
    db_session.execute(text("DELETE FROM webhook_deliveries"))
    # organizations/organization_members (Phase 17) are created automatically
    # alongside an Installation (see app/tenancy/provisioning.py) and must be
    # cleared before it, or the installations delete below violates the
    # organizations_installation_id_fkey foreign key.
    db_session.execute(text("DELETE FROM organization_members"))
    db_session.execute(text("DELETE FROM organizations"))
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


def test_installation_created_with_selected_repos_registers_them(db_session) -> None:
    """Regression test: a repository chosen during the install flow (not
    added later via the installation settings) arrives in the `installation`
    event's own `repositories` field when repository_selection is
    "selected" - this must register a Repository row immediately, not only
    on a later `installation_repositories` event.
    """
    delivery_id = _delivery_id()
    db_session.add(WebhookDelivery(delivery_id=delivery_id, event_type="installation"))
    db_session.commit()

    payload = {
        "action": "created",
        "installation": {
            "id": 3001,
            "account": {"login": "acme", "type": "User"},
            "repository_selection": "selected",
        },
        "repositories": [{"id": 7001, "full_name": "acme/widgets"}],
    }

    process_github_webhook.run(delivery_id=delivery_id, event_type="installation", payload=payload)

    repo = db_session.query(Repository).filter_by(github_repo_id=7001).one()
    assert repo.full_name == "acme/widgets"
    assert repo.is_active is True


def test_installation_created_with_all_repos_fetches_via_api(db_session) -> None:
    """Regression test: when repository_selection is "all", GitHub omits
    `repositories` from the payload entirely - the app must call the
    installation repositories API to enumerate them instead of silently
    registering nothing.
    """
    delivery_id = _delivery_id()
    db_session.add(WebhookDelivery(delivery_id=delivery_id, event_type="installation"))
    db_session.commit()

    payload = {
        "action": "created",
        "installation": {
            "id": 3002,
            "account": {"login": "acme", "type": "Organization"},
            "repository_selection": "all",
        },
    }

    mock_client = MagicMock()
    mock_client.__enter__.return_value = mock_client
    mock_client.__exit__.return_value = False
    mock_client.list_installation_repositories.return_value = [
        {"id": 7002, "full_name": "acme/gizmos"}
    ]

    with (
        patch(
            "app.tasks.github_webhook.get_installation_access_token", return_value="fake-token"
        ),
        patch("app.tasks.github_webhook.GitHubClient", return_value=mock_client),
    ):
        process_github_webhook.run(
            delivery_id=delivery_id, event_type="installation", payload=payload
        )

    repo = db_session.query(Repository).filter_by(github_repo_id=7002).one()
    assert repo.full_name == "acme/gizmos"
    assert repo.is_active is True


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


def test_installation_deleted_purges_repo_index(db_session) -> None:
    installation = Installation(
        github_installation_id=1001, account_login="acme", account_type="Organization"
    )
    db_session.add(installation)
    db_session.flush()
    repo = Repository(
        installation_id=installation.id,
        github_repo_id=556,
        owner="acme",
        name="widgets",
        full_name="acme/widgets",
        is_active=True,
    )
    db_session.add(repo)
    db_session.flush()
    db_session.add(
        RepoFileIndex(
            repository_id=repo.id,
            path="app.py",
            content_sha="sha",
            last_seen_commit_sha="sha1",
        )
    )
    db_session.add(
        RepoSymbolChunk(
            repository_id=repo.id,
            path="app.py",
            symbol="changed",
            kind="function",
            start_line=1,
            end_line=2,
            content_sha="sha",
            last_seen_commit_sha="sha1",
        )
    )
    db_session.commit()

    delivery_id = _delivery_id()
    db_session.add(WebhookDelivery(delivery_id=delivery_id, event_type="installation"))
    db_session.commit()

    payload = {"action": "deleted", "installation": {"id": 1001, "account": {}}}
    process_github_webhook.run(delivery_id=delivery_id, event_type="installation", payload=payload)

    assert db_session.query(RepoFileIndex).filter_by(repository_id=repo.id).count() == 0
    assert db_session.query(RepoSymbolChunk).filter_by(repository_id=repo.id).count() == 0


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


def test_installation_repositories_removed_purges_repo_index(db_session) -> None:
    installation = Installation(
        github_installation_id=3001, account_login="acme", account_type="Organization"
    )
    db_session.add(installation)
    db_session.flush()
    repo = Repository(
        installation_id=installation.id,
        github_repo_id=889,
        owner="acme",
        name="sprockets",
        full_name="acme/sprockets",
        is_active=True,
    )
    db_session.add(repo)
    db_session.flush()
    db_session.add(
        RepoSymbolChunk(
            repository_id=repo.id,
            path="app.py",
            symbol="changed",
            kind="function",
            start_line=1,
            end_line=2,
            content_sha="sha",
            last_seen_commit_sha="sha1",
        )
    )
    db_session.commit()

    delivery_id = _delivery_id()
    db_session.add(WebhookDelivery(delivery_id=delivery_id, event_type="installation_repositories"))
    db_session.commit()

    payload = {
        "action": "removed",
        "installation": {"id": 3001},
        "repositories_added": [],
        "repositories_removed": [{"id": 889, "full_name": "acme/sprockets"}],
    }
    process_github_webhook.run(
        delivery_id=delivery_id, event_type="installation_repositories", payload=payload
    )

    assert db_session.query(RepoSymbolChunk).filter_by(repository_id=repo.id).count() == 0


def test_unhandled_event_type_is_marked_processed(db_session) -> None:
    delivery_id = _delivery_id()
    db_session.add(WebhookDelivery(delivery_id=delivery_id, event_type="push"))
    db_session.commit()

    process_github_webhook.run(delivery_id=delivery_id, event_type="push", payload={})

    delivery = db_session.query(WebhookDelivery).filter_by(delivery_id=delivery_id).one()
    assert delivery.status == "processed"
