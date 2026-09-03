import uuid
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import text

from app.github.pr_automation import AUTOMATED_SECTION_START
from app.models import Installation, PullRequest, Repository, WebhookDelivery
from app.tasks.github_webhook import process_github_webhook


@pytest.fixture(autouse=True)
def _cleanup(db_session):
    yield
    db_session.execute(text("DELETE FROM tool_runs"))
    db_session.execute(text("DELETE FROM changed_files"))
    db_session.execute(text("DELETE FROM diff_snapshots"))
    db_session.execute(text("DELETE FROM pull_requests"))
    db_session.execute(text("DELETE FROM repositories"))
    db_session.execute(text("DELETE FROM webhook_deliveries"))
    db_session.execute(text("DELETE FROM installations"))
    db_session.commit()


@pytest.fixture
def installation(db_session) -> Installation:
    installation = Installation(
        github_installation_id=4242, account_login="acme", account_type="Organization"
    )
    db_session.add(installation)
    db_session.commit()
    return installation


@pytest.fixture
def repository(db_session, installation) -> Repository:
    repository = Repository(
        installation_id=installation.id,
        github_repo_id=8181,
        owner="acme",
        name="widgets",
        full_name="acme/widgets",
        default_branch="main",
        is_active=True,
    )
    db_session.add(repository)
    db_session.commit()
    return repository


def _delivery_id() -> str:
    return str(uuid.uuid4())


def _push_payload(
    ref: str = "refs/heads/foundations",
    after: str = "sha-new",
    deleted: bool = False,
    sender_type: str = "User",
    commits: list | None = None,
) -> dict:
    return {
        "ref": ref,
        "after": after,
        "deleted": deleted,
        "sender": {"type": sender_type},
        "installation": {"id": 4242},
        "repository": {"id": 8181},
        "commits": commits if commits is not None else [{"id": "sha-new", "message": "fix bug"}],
    }


def _run_push(db_session, payload: dict, mock_client: MagicMock) -> None:
    delivery_id = _delivery_id()
    db_session.add(WebhookDelivery(delivery_id=delivery_id, event_type="push"))
    db_session.commit()

    with (
        patch(
            "app.tasks.github_webhook.get_installation_access_token", return_value="fake-token"
        ),
        patch("app.tasks.github_webhook.GitHubClient", return_value=mock_client),
    ):
        process_github_webhook.run(delivery_id=delivery_id, event_type="push", payload=payload)

    delivery = db_session.query(WebhookDelivery).filter_by(delivery_id=delivery_id).one()
    assert delivery.status == "processed"


def _client_with_no_config_no_existing_pr(head_sha: str) -> MagicMock:
    client = MagicMock()
    client.__enter__.return_value = client
    client.__exit__.return_value = False
    client.get_file_contents.return_value = None
    client.get_ref_sha.return_value = head_sha
    client.list_open_pull_requests.return_value = []
    client.create_pull_request.return_value = {
        "number": 99,
        "state": "open",
        "base": {"sha": "base-sha"},
    }
    client.compare_commits.return_value = {
        "merge_base_commit": {"sha": "merge-base-sha"},
        "commits": [],
        "files": [],
    }
    return client


def test_push_to_source_branch_creates_pull_request(db_session, repository) -> None:
    client = _client_with_no_config_no_existing_pr("sha-new")
    _run_push(db_session, _push_payload(), client)

    client.create_pull_request.assert_called_once()
    _, kwargs = client.create_pull_request.call_args
    assert kwargs["head"] == "foundations"
    assert kwargs["base"] == "main"
    assert AUTOMATED_SECTION_START in kwargs["body"]

    pr = db_session.query(PullRequest).filter_by(repository_id=repository.id).one()
    assert pr.github_pr_number == 99
    assert pr.head_sha == "sha-new"


def test_push_to_unrelated_branch_does_nothing(db_session, repository) -> None:
    # .reviewrush.yml can override which branch is "source", so it must be read
    # before an unmonitored branch can be ruled out — but nothing beyond that
    # read should happen for a branch that isn't the resolved source.
    client = _client_with_no_config_no_existing_pr("sha-new")
    _run_push(db_session, _push_payload(ref="refs/heads/some-other-branch"), client)

    client.get_ref_sha.assert_not_called()
    client.create_pull_request.assert_not_called()
    assert db_session.query(PullRequest).count() == 0


def test_push_from_bot_sender_is_ignored(db_session, repository) -> None:
    client = _client_with_no_config_no_existing_pr("sha-new")
    _run_push(db_session, _push_payload(sender_type="Bot"), client)

    client.get_file_contents.assert_not_called()
    client.create_pull_request.assert_not_called()


def test_deleted_branch_does_not_create_pull_request(db_session, repository) -> None:
    client = _client_with_no_config_no_existing_pr("sha-new")
    _run_push(db_session, _push_payload(deleted=True), client)

    client.get_file_contents.assert_not_called()
    client.create_pull_request.assert_not_called()


def test_stale_push_does_not_create_pull_request(db_session, repository) -> None:
    client = _client_with_no_config_no_existing_pr("sha-newer")
    _run_push(db_session, _push_payload(after="sha-old"), client)

    client.create_pull_request.assert_not_called()
    assert db_session.query(PullRequest).count() == 0


def test_repeat_push_updates_existing_open_pr(db_session, repository) -> None:
    client = _client_with_no_config_no_existing_pr("sha-1")
    _run_push(db_session, _push_payload(after="sha-1"), client)
    assert db_session.query(PullRequest).count() == 1

    second_client = MagicMock()
    second_client.__enter__.return_value = second_client
    second_client.__exit__.return_value = False
    second_client.get_file_contents.return_value = None
    second_client.get_ref_sha.return_value = "sha-2"
    second_client.list_open_pull_requests.return_value = [
        {"number": 99, "body": "Human notes.", "state": "open", "base": {"sha": "base-sha"}}
    ]
    second_client.update_pull_request.return_value = {
        "number": 99,
        "state": "open",
        "base": {"sha": "base-sha"},
    }
    second_client.compare_commits.return_value = {
        "merge_base_commit": {"sha": "merge-base-sha"},
        "commits": [],
        "files": [],
    }
    _run_push(db_session, _push_payload(after="sha-2"), second_client)

    second_client.create_pull_request.assert_not_called()
    second_client.update_pull_request.assert_called_once()

    pr = db_session.query(PullRequest).filter_by(repository_id=repository.id).one()
    assert pr.head_sha == "sha-2"


def test_repo_config_overrides_default_branches(db_session, repository) -> None:
    client = _client_with_no_config_no_existing_pr("sha-1")
    client.get_file_contents.return_value = "branches:\n  source: dev\n  target: release\n"
    _run_push(
        db_session, _push_payload(ref="refs/heads/dev", after="sha-1"), client
    )

    client.create_pull_request.assert_called_once()
    _, kwargs = client.create_pull_request.call_args
    assert kwargs["head"] == "dev"
    assert kwargs["base"] == "release"
