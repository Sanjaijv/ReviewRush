from unittest.mock import MagicMock

from app.models import Organization
from app.tenancy.deletion import delete_organization_data
from app.tenancy.export import export_organization_data


def _org() -> Organization:
    return Organization(id=1, installation_id=1, slug="acme", name="acme")


def _db_with_repository_ids(repository_ids: list[int]) -> MagicMock:
    db = MagicMock()
    repos = [MagicMock(id=i) for i in repository_ids]
    db.query.return_value.filter_by.return_value.all.return_value = repos
    return db


def test_export_bundle_includes_organization_and_is_scoped_to_its_repositories() -> None:
    db = _db_with_repository_ids([1, 2])
    # Every other query (.filter(...).all()) returns [] for this smoke test -
    # only the shape of the bundle is asserted, not real row content.
    db.query.return_value.filter.return_value.all.return_value = []

    bundle = export_organization_data(db, _org())

    assert bundle["organization"]["slug"] == "acme"
    assert set(bundle.keys()) >= {
        "organization",
        "repositories",
        "pull_requests",
        "diff_snapshots",
        "ai_reviews",
        "ai_findings",
        "tool_runs",
        "policy_decisions",
        "review_comments",
        "merge_attempts",
        "audit_events",
    }


def test_delete_writes_audit_event_before_deleting_rows() -> None:
    db = _db_with_repository_ids([1])
    db.query.return_value.filter.return_value.delete.return_value = 0
    db.query.return_value.filter.return_value.all.return_value = []

    calls: list[str] = []
    db.add.side_effect = lambda obj: calls.append("audit_event_added")
    db.query.return_value.filter.return_value.delete.side_effect = (
        lambda *a, **k: calls.append("rows_deleted") or 0
    )

    delete_organization_data(db, _org(), actor_user_id=1, actor_login="octocat")

    assert calls[0] == "audit_event_added"
    assert "rows_deleted" in calls


def test_delete_with_no_repositories_still_records_audit_event() -> None:
    db = _db_with_repository_ids([])

    counts = delete_organization_data(db, _org(), actor_user_id=1, actor_login="octocat")

    assert counts == {"repositories": 0}
    db.add.assert_called_once()
    db.commit.assert_called()
