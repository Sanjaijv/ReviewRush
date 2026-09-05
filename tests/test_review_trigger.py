from unittest.mock import MagicMock, patch

from app.models import DiffSnapshot
from app.tasks.review_trigger import supersede_previous_snapshots, trigger_review_for_commit


def test_trigger_review_for_commit_returns_none_when_target_branch_has_no_head() -> None:
    db = MagicMock()
    client = MagicMock()
    client.get_ref_sha.return_value = None
    repository = MagicMock(owner="acme", name="widgets", full_name="acme/widgets")

    with patch("app.tasks.review_trigger.build_diff_snapshot") as build_mock:
        result = trigger_review_for_commit(db, client, repository, "main", "sha1", None)

    assert result is None
    build_mock.assert_not_called()


def test_trigger_review_for_commit_builds_snapshot_and_queues_analysis() -> None:
    db = MagicMock()
    client = MagicMock()
    client.get_ref_sha.return_value = "base-sha"
    repository = MagicMock(id=1, owner="acme", name="widgets", full_name="acme/widgets")
    pull_request = MagicMock(id=9)
    snapshot = DiffSnapshot(id=5, repository_id=1, head_sha="newsha", base_sha="base-sha")

    with (
        patch("app.tasks.review_trigger.build_diff_snapshot", return_value=snapshot) as build_mock,
        patch("app.tasks.review_trigger.supersede_previous_snapshots") as supersede_mock,
        patch("app.tasks.review_trigger.start_check_run") as start_check_mock,
        patch("app.tasks.analysis.run_analysis_pipeline_task") as analysis_task_mock,
    ):
        result = trigger_review_for_commit(
            db, client, repository, "main", "newsha", pull_request
        )

    assert result is snapshot
    build_mock.assert_called_once_with(
        db=db, client=client, repository=repository, base_sha="base-sha", head_sha="newsha",
        pull_request_id=9,
    )
    supersede_mock.assert_called_once_with(db, repository, snapshot)
    start_check_mock.assert_called_once_with(client, repository, snapshot, db)
    analysis_task_mock.delay.assert_called_once_with(1, 5)


def test_trigger_review_for_commit_passes_none_pull_request_id_when_no_pr() -> None:
    db = MagicMock()
    client = MagicMock()
    client.get_ref_sha.return_value = "base-sha"
    repository = MagicMock(id=1, owner="acme", name="widgets", full_name="acme/widgets")
    snapshot = DiffSnapshot(id=5, repository_id=1, head_sha="newsha", base_sha="base-sha")

    with (
        patch("app.tasks.review_trigger.build_diff_snapshot", return_value=snapshot) as build_mock,
        patch("app.tasks.review_trigger.supersede_previous_snapshots"),
        patch("app.tasks.review_trigger.start_check_run"),
        patch("app.tasks.analysis.run_analysis_pipeline_task"),
    ):
        trigger_review_for_commit(db, client, repository, "main", "newsha", None)

    assert build_mock.call_args.kwargs["pull_request_id"] is None


def test_supersede_previous_snapshots_cancels_stale_complete_snapshots() -> None:
    db = MagicMock()
    stale = DiffSnapshot(id=1, repository_id=1, head_sha="old", base_sha="b", status="complete")
    new_snapshot = DiffSnapshot(id=2, repository_id=1, head_sha="new", base_sha="b")
    db.query.return_value.filter.return_value.all.return_value = [stale]
    repository = MagicMock(id=1, full_name="acme/widgets")

    supersede_previous_snapshots(db, repository, new_snapshot)

    assert stale.status == "cancelled"
    db.commit.assert_called_once()


def test_supersede_previous_snapshots_noop_when_nothing_stale() -> None:
    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = []
    new_snapshot = DiffSnapshot(id=2, repository_id=1, head_sha="new", base_sha="b")
    repository = MagicMock(id=1, full_name="acme/widgets")

    supersede_previous_snapshots(db, repository, new_snapshot)

    db.commit.assert_not_called()
