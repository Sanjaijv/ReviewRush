from unittest.mock import MagicMock

from sqlalchemy.exc import IntegrityError

from app.diffs.limits import DiffLimits
from app.diffs.service import build_diff_snapshot
from app.models import DiffSnapshot


class _FakeRepository:
    def __init__(self):
        self.id = 1
        self.owner = "acme"
        self.name = "widgets"
        self.full_name = "acme/widgets"


def _db_with_no_existing_snapshot() -> MagicMock:
    db = MagicMock()
    db.query.return_value.filter_by.return_value.one_or_none.return_value = None
    return db


def _default_limits() -> DiffLimits:
    return DiffLimits(
        max_files=100,
        max_file_patch_bytes=100_000,
        max_total_changed_lines=10_000,
        max_total_prompt_bytes=1_000_000,
    )


def test_new_snapshot_stamps_pull_request_id_when_given() -> None:
    db = _db_with_no_existing_snapshot()
    client = MagicMock()
    client.get_file_contents.return_value = None
    client.compare_commits.return_value = {
        "merge_base_commit": {"sha": "base123"},
        "commits": [],
        "files": [],
    }
    repository = _FakeRepository()

    result = build_diff_snapshot(
        db, client, repository, base_sha="main-sha", head_sha="sha1", pull_request_id=42,
    )

    assert result.pull_request_id == 42


def test_new_snapshot_pull_request_id_defaults_to_none() -> None:
    db = _db_with_no_existing_snapshot()
    client = MagicMock()
    client.get_file_contents.return_value = None
    client.compare_commits.return_value = {
        "merge_base_commit": {"sha": "base123"},
        "commits": [],
        "files": [],
    }
    repository = _FakeRepository()

    result = build_diff_snapshot(db, client, repository, base_sha="main-sha", head_sha="sha1")

    assert result.pull_request_id is None


def test_returns_existing_snapshot_without_recomputing() -> None:
    db = MagicMock()
    existing = DiffSnapshot(repository_id=1, head_sha="sha1", base_sha="main-sha")
    db.query.return_value.filter_by.return_value.one_or_none.return_value = existing
    client = MagicMock()
    repository = _FakeRepository()

    result = build_diff_snapshot(db, client, repository, base_sha="main-sha", head_sha="sha1")

    assert result is existing
    client.compare_commits.assert_not_called()
    db.add.assert_not_called()


def test_builds_snapshot_classifying_added_modified_removed_renamed_files() -> None:
    db = _db_with_no_existing_snapshot()
    client = MagicMock()
    client.get_file_contents.return_value = None
    client.compare_commits.return_value = {
        "merge_base_commit": {"sha": "base123"},
        "commits": [
            {
                "sha": "c1",
                "commit": {
                    "message": "fix: correct off-by-one\n\nlonger body",
                    "author": {"name": "Dev One", "date": "2026-09-01T00:00:00Z"},
                },
                "author": {"login": "devone"},
            }
        ],
        "files": [
            {
                "filename": "app/new_module.py",
                "status": "added",
                "additions": 3,
                "deletions": 0,
                "changes": 3,
                "patch": "@@ -0,0 +1,3 @@\n+line1\n+line2\n+line3",
            },
            {
                "filename": "app/existing.py",
                "status": "modified",
                "additions": 1,
                "deletions": 1,
                "changes": 2,
                "patch": "@@ -1,2 +1,2 @@\n context\n-old\n+new",
            },
            {
                "filename": "app/gone.py",
                "status": "removed",
                "additions": 0,
                "deletions": 5,
                "changes": 5,
                "patch": "@@ -1,5 +0,0 @@\n-a\n-b\n-c\n-d\n-e",
            },
            {
                "filename": "app/renamed_new.py",
                "previous_filename": "app/renamed_old.py",
                "status": "renamed",
                "additions": 0,
                "deletions": 0,
                "changes": 0,
            },
        ],
    }
    repository = _FakeRepository()

    snapshot = build_diff_snapshot(
        db, client, repository, base_sha="main-sha", head_sha="head-sha",
        limits=_default_limits(),
    )

    assert snapshot.status == "complete"
    assert snapshot.merge_base_sha == "base123"
    assert snapshot.file_count == 4
    assert snapshot.total_additions == 4
    assert snapshot.total_deletions == 6
    assert snapshot.commits == [
        {
            "sha": "c1",
            "message": "fix: correct off-by-one",
            "author_login": "devone",
            "author_name": "Dev One",
            "authored_at": "2026-09-01T00:00:00Z",
        }
    ]
    db.add.assert_called_once_with(snapshot)
    db.commit.assert_called_once()

    by_new_path = {f.new_path: f for f in snapshot.changed_files}
    added = by_new_path["app/new_module.py"]
    assert added.status == "added"
    assert added.old_path is None
    assert added.excluded_from_ai is False

    removed = [f for f in snapshot.changed_files if f.status == "removed"][0]
    assert removed.old_path == "app/gone.py"
    assert removed.new_path is None

    renamed = by_new_path["app/renamed_new.py"]
    assert renamed.old_path == "app/renamed_old.py"
    assert renamed.status == "renamed"


def test_binary_file_without_patch_is_excluded_from_ai() -> None:
    db = _db_with_no_existing_snapshot()
    client = MagicMock()
    client.get_file_contents.return_value = None
    client.compare_commits.return_value = {
        "merge_base_commit": {"sha": "base123"},
        "files": [
            {
                "filename": "assets/logo.png",
                "status": "modified",
                "additions": 0,
                "deletions": 0,
                "changes": 0,
            }
        ],
    }
    repository = _FakeRepository()

    snapshot = build_diff_snapshot(
        db, client, repository, base_sha="main-sha", head_sha="head-sha",
        limits=_default_limits(),
    )

    changed_file = snapshot.changed_files[0]
    assert changed_file.is_binary is True
    assert changed_file.patch is None
    assert changed_file.excluded_from_ai is True


def test_lockfile_is_excluded_from_ai_but_not_treated_as_binary() -> None:
    db = _db_with_no_existing_snapshot()
    client = MagicMock()
    client.get_file_contents.return_value = None
    client.compare_commits.return_value = {
        "merge_base_commit": {"sha": "base123"},
        "files": [
            {
                "filename": "package-lock.json",
                "status": "modified",
                "additions": 20,
                "deletions": 10,
                "changes": 30,
                "patch": "@@ -1,2 +1,2 @@\n context\n-old\n+new",
            }
        ],
    }
    repository = _FakeRepository()

    snapshot = build_diff_snapshot(
        db, client, repository, base_sha="main-sha", head_sha="head-sha",
        limits=_default_limits(),
    )

    changed_file = snapshot.changed_files[0]
    assert changed_file.is_generated is True
    assert changed_file.is_binary is False
    assert changed_file.excluded_from_ai is True
    assert changed_file.patch is not None


def test_oversized_diff_is_marked_for_human_review_not_truncated() -> None:
    db = _db_with_no_existing_snapshot()
    client = MagicMock()
    client.get_file_contents.return_value = None
    client.compare_commits.return_value = {
        "merge_base_commit": {"sha": "base123"},
        "files": [
            {
                "filename": f"app/file_{i}.py",
                "status": "modified",
                "additions": 1,
                "deletions": 0,
                "changes": 1,
                "patch": "@@ -1,1 +1,2 @@\n context\n+new",
            }
            for i in range(3)
        ],
    }
    repository = _FakeRepository()
    tight_limits = DiffLimits(
        max_files=2,
        max_file_patch_bytes=100_000,
        max_total_changed_lines=10_000,
        max_total_prompt_bytes=1_000_000,
    )

    snapshot = build_diff_snapshot(
        db, client, repository, base_sha="main-sha", head_sha="head-sha",
        limits=tight_limits,
    )

    assert snapshot.status == "oversized"
    assert snapshot.file_count == 3
    assert len(snapshot.changed_files) == 3


def test_large_text_file_without_patch_is_truncated_not_binary() -> None:
    db = _db_with_no_existing_snapshot()
    client = MagicMock()
    client.get_file_contents.return_value = None
    client.compare_commits.return_value = {
        "merge_base_commit": {"sha": "base123"},
        "files": [
            {
                "filename": "data/big_dump.sql",
                "status": "modified",
                "additions": 50000,
                "deletions": 0,
                "changes": 50000,
            }
        ],
    }
    repository = _FakeRepository()

    snapshot = build_diff_snapshot(
        db, client, repository, base_sha="main-sha", head_sha="head-sha",
        limits=_default_limits(),
    )

    changed_file = snapshot.changed_files[0]
    assert changed_file.is_binary is False
    assert changed_file.patch_truncated is True
    assert changed_file.patch is None
    assert snapshot.truncated is True


def test_concurrent_build_falls_back_to_existing_row_on_integrity_error() -> None:
    db = MagicMock()
    existing_after_race = DiffSnapshot(repository_id=1, head_sha="head-sha", base_sha="main-sha")
    db.query.return_value.filter_by.return_value.one_or_none.side_effect = [None]
    db.query.return_value.filter_by.return_value.one.return_value = existing_after_race
    db.commit.side_effect = IntegrityError("insert", {}, Exception("duplicate"))

    client = MagicMock()
    client.get_file_contents.return_value = None
    client.compare_commits.return_value = {"merge_base_commit": {"sha": "base123"}, "files": []}
    repository = _FakeRepository()

    result = build_diff_snapshot(
        db, client, repository, base_sha="main-sha", head_sha="head-sha",
        limits=_default_limits(),
    )

    assert result is existing_after_race
    db.rollback.assert_called_once()


def test_submodule_path_is_detected_via_gitmodules() -> None:
    db = _db_with_no_existing_snapshot()
    client = MagicMock()
    client.get_file_contents.return_value = (
        '[submodule "libs/foo"]\n\tpath = libs/foo\n\turl = https://example.com/foo.git\n'
    )
    client.compare_commits.return_value = {
        "merge_base_commit": {"sha": "base123"},
        "files": [
            {
                "filename": "libs/foo",
                "status": "modified",
                "additions": 0,
                "deletions": 0,
                "changes": 0,
            }
        ],
    }
    repository = _FakeRepository()

    snapshot = build_diff_snapshot(
        db, client, repository, base_sha="main-sha", head_sha="head-sha",
        limits=_default_limits(),
    )

    changed_file = snapshot.changed_files[0]
    assert changed_file.is_submodule is True
    assert changed_file.is_binary is False
    assert changed_file.excluded_from_ai is True
    assert changed_file.patch is None


def test_commit_metadata_is_capped_and_missing_fields_are_tolerated() -> None:
    db = _db_with_no_existing_snapshot()
    client = MagicMock()
    client.get_file_contents.return_value = None
    client.compare_commits.return_value = {
        "merge_base_commit": {"sha": "base123"},
        "commits": [{"sha": f"c{i}", "commit": {}} for i in range(150)],
        "files": [],
    }
    repository = _FakeRepository()

    snapshot = build_diff_snapshot(
        db, client, repository, base_sha="main-sha", head_sha="head-sha",
        limits=_default_limits(),
    )

    assert len(snapshot.commits) == 100
    assert snapshot.commits[0] == {
        "sha": "c0",
        "message": "",
        "author_login": None,
        "author_name": None,
        "authored_at": None,
    }
