from unittest.mock import MagicMock

from app.evaluation.dataset import build_dataset_version
from app.models import (
    AIFinding,
    ChangedFile,
    DiffSnapshot,
    EvalDatasetItem,
    EvalDatasetVersion,
    FindingFeedback,
    Repository,
)


def _row(finding_id: int, file_path: str, patch: str, category: str = "security") -> tuple:
    feedback = FindingFeedback(
        id=finding_id, repository_id=1, ai_finding_id=finding_id, reaction="useful",
        consent=True, retention_days=365, actor_user_id=1, actor_login="octocat",
    )
    finding = AIFinding(
        id=finding_id, ai_review_id=1, repository_id=1, file=file_path,
        start_line=3, end_line=3, severity="high", category=category, title="t", evidence="e",
    )
    diff_snapshot = DiffSnapshot(id=1, repository_id=1, head_sha="sha1", base_sha="sha0")
    changed_file = ChangedFile(
        diff_snapshot_id=1, new_path=file_path, status="modified", patch=patch
    )
    diff_snapshot.changed_files = [changed_file]
    repository = Repository(
        id=1, installation_id=1, github_repo_id=1, owner="acme", name="w", full_name="acme/w"
    )
    return feedback, finding, diff_snapshot, repository


def _setup_db(rows: list[tuple], next_version_scalar: int | None) -> MagicMock:
    db = MagicMock()
    db.query.return_value.scalar.return_value = next_version_scalar
    joined = (
        db.query.return_value.join.return_value.join.return_value.join.return_value.join
    )
    joined.return_value.filter.return_value.all.return_value = rows
    return db


def _added(db: MagicMock, cls: type) -> list:
    return [c.args[0] for c in db.add.call_args_list if isinstance(c.args[0], cls)]


def test_build_dataset_version_starts_at_one_when_none_exist() -> None:
    db = _setup_db([_row(1, "a.py", "@@ -1,1 +1,1 @@\n-x\n+y")], next_version_scalar=None)

    version = build_dataset_version(db, actor_user_id=1, actor_login="octocat")

    versions_added = _added(db, EvalDatasetVersion)
    assert versions_added[0].version == 1
    assert version.item_count == 1


def test_build_dataset_version_increments_from_existing_max() -> None:
    db = _setup_db([_row(1, "a.py", "@@ -1,1 +1,1 @@\n-x\n+y")], next_version_scalar=4)

    build_dataset_version(db, actor_user_id=1, actor_login="octocat")

    versions_added = _added(db, EvalDatasetVersion)
    assert versions_added[0].version == 5


def test_build_dataset_version_redacts_diff_text_and_pseudonymizes_repo() -> None:
    patch = "@@ -1,1 +1,1 @@\n-old\n+token = AKIAABCDEFGHIJKLMNOP"
    db = _setup_db([_row(1, "a.py", patch)], next_version_scalar=0)

    build_dataset_version(db, actor_user_id=1, actor_login="octocat")

    items = _added(db, EvalDatasetItem)
    assert len(items) == 1
    assert "AKIAABCDEFGHIJKLMNOP" not in items[0].diff_text
    assert items[0].repository_ref != "acme/w"
    assert items[0].expected_findings == [{"category": "security", "severity": "high", "line": 3}]


def test_build_dataset_version_deduplicates_repeated_finding() -> None:
    row = _row(1, "a.py", "@@ -1,1 +1,1 @@\n-x\n+y")
    db = _setup_db([row, row], next_version_scalar=0)

    version = build_dataset_version(db, actor_user_id=1, actor_login="octocat")

    assert version.item_count == 1
    assert len(_added(db, EvalDatasetItem)) == 1


def test_build_dataset_version_skips_finding_with_no_patch() -> None:
    feedback, finding, diff_snapshot, repository = _row(1, "a.py", "")
    diff_snapshot.changed_files[0].patch = None
    db = _setup_db([(feedback, finding, diff_snapshot, repository)], next_version_scalar=0)

    version = build_dataset_version(db, actor_user_id=1, actor_login="octocat")

    assert version.item_count == 0
    assert _added(db, EvalDatasetItem) == []
