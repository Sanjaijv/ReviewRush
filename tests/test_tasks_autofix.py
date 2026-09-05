from unittest.mock import MagicMock, patch

from app.tasks.autofix import run_auto_fix_task, run_manual_fix_task


def _installation_repo() -> MagicMock:
    installation = MagicMock(github_installation_id=1)
    return MagicMock(installation=installation)


def test_run_auto_fix_task_skips_when_repository_or_snapshot_missing() -> None:
    db = MagicMock()
    db.get.return_value = None

    with patch("app.tasks.autofix.SessionLocal", return_value=db):
        result = run_auto_fix_task(repository_id=1, diff_snapshot_id=1)

    assert result == "skipped"


def test_run_auto_fix_task_skips_cancelled_snapshot() -> None:
    db = MagicMock()
    repository = _installation_repo()
    diff_snapshot = MagicMock(status="cancelled")
    db.get.side_effect = [repository, diff_snapshot]

    with patch("app.tasks.autofix.SessionLocal", return_value=db):
        result = run_auto_fix_task(repository_id=1, diff_snapshot_id=1)

    assert result == "cancelled"


def test_run_manual_fix_task_skips_when_finding_missing() -> None:
    db = MagicMock()
    db.get.side_effect = [MagicMock(), MagicMock(), None]  # repository, diff_snapshot, finding

    with patch("app.tasks.autofix.SessionLocal", return_value=db):
        result = run_manual_fix_task(
            repository_id=1, diff_snapshot_id=1, ai_finding_id=1,
            review_comment_id=None, actor_login="octocat",
            current_comment_body="- [x] Apply this fix",
        )

    assert result == "skipped"


def test_run_manual_fix_task_triggers_review_when_committed() -> None:
    db = MagicMock()
    repository = _installation_repo()
    diff_snapshot = MagicMock(pull_request_id=9)
    finding = MagicMock()
    pull_request = MagicMock(base_branch="main")
    db.get.side_effect = [repository, diff_snapshot, finding, pull_request]
    attempt = MagicMock(status="committed", commit_sha="abc123")

    with (
        patch("app.tasks.autofix.SessionLocal", return_value=db),
        patch("app.tasks.autofix.get_installation_access_token", return_value="tok"),
        patch("app.tasks.autofix.GitHubClient"),
        patch("app.tasks.autofix.run_manual_fix", return_value=attempt),
        patch("app.tasks.autofix.trigger_review_for_commit") as trigger_mock,
    ):
        result = run_manual_fix_task(
            repository_id=1, diff_snapshot_id=1, ai_finding_id=1,
            review_comment_id=None, actor_login="octocat",
            current_comment_body="- [x] Apply this fix",
        )

    assert result == "committed"
    trigger_mock.assert_called_once()
    args = trigger_mock.call_args.args
    assert args[2] is repository
    assert args[3] == "main"
    assert args[4] == "abc123"
    assert args[5] is pull_request


def test_run_manual_fix_task_does_not_trigger_review_when_not_committed() -> None:
    db = MagicMock()
    repository = _installation_repo()
    diff_snapshot = MagicMock(pull_request_id=9)
    finding = MagicMock()
    db.get.side_effect = [repository, diff_snapshot, finding]
    attempt = MagicMock(status="error", commit_sha=None)

    with (
        patch("app.tasks.autofix.SessionLocal", return_value=db),
        patch("app.tasks.autofix.get_installation_access_token", return_value="tok"),
        patch("app.tasks.autofix.GitHubClient"),
        patch("app.tasks.autofix.run_manual_fix", return_value=attempt),
        patch("app.tasks.autofix.trigger_review_for_commit") as trigger_mock,
    ):
        result = run_manual_fix_task(
            repository_id=1, diff_snapshot_id=1, ai_finding_id=1,
            review_comment_id=None, actor_login="octocat",
            current_comment_body="- [x] Apply this fix",
        )

    assert result == "error"
    trigger_mock.assert_not_called()


def test_run_manual_fix_task_returns_skipped_when_run_manual_fix_returns_none() -> None:
    db = MagicMock()
    repository = _installation_repo()
    diff_snapshot = MagicMock(pull_request_id=None)
    finding = MagicMock()
    db.get.side_effect = [repository, diff_snapshot, finding]

    with (
        patch("app.tasks.autofix.SessionLocal", return_value=db),
        patch("app.tasks.autofix.get_installation_access_token", return_value="tok"),
        patch("app.tasks.autofix.GitHubClient"),
        patch("app.tasks.autofix.run_manual_fix", return_value=None),
        patch("app.tasks.autofix.trigger_review_for_commit") as trigger_mock,
    ):
        result = run_manual_fix_task(
            repository_id=1, diff_snapshot_id=1, ai_finding_id=1,
            review_comment_id=None, actor_login="octocat",
            current_comment_body="- [x] Apply this fix",
        )

    assert result == "skipped"
    trigger_mock.assert_not_called()
