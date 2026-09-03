from pathlib import Path
from unittest.mock import MagicMock, patch

from app.analysis.workspace import Workspace
from app.config import Settings
from app.context.service import build_repository_context_for_snapshot
from app.models import ChangedFile, DiffSnapshot, RepoContextSnapshot

_PATCH = "@@ -1,2 +1,3 @@\n context\n+def changed():\n+    return 1"


class _FakeInstallation:
    github_installation_id = 1


class _FakeRepository:
    def __init__(self) -> None:
        self.id = 1
        self.owner = "acme"
        self.name = "widgets"
        self.full_name = "acme/widgets"
        self.installation = _FakeInstallation()


def _diff_snapshot() -> DiffSnapshot:
    snapshot = DiffSnapshot(id=1, repository_id=1, head_sha="sha1", base_sha="mainsha")
    snapshot.changed_files = [
        ChangedFile(new_path="app.py", old_path="app.py", status="modified", patch=_PATCH)
    ]
    return snapshot


def _db_with_no_existing_rows() -> MagicMock:
    db = MagicMock()
    db.query.return_value.filter_by.return_value.one_or_none.return_value = None
    return db


def _settings(**overrides) -> Settings:
    base = dict(context_enabled=True)
    base.update(overrides)
    return Settings(**base)


def _run(db, settings, workspace_root: Path):
    workspace = Workspace(run_subdir="run1", host_path=workspace_root)
    with (
        patch("app.context.service.get_settings", return_value=settings),
        patch("app.context.service.get_installation_access_token", return_value="tok"),
        patch("app.context.service.GitHubClient") as github_client_cls,
        patch("app.context.service.workspace_for") as workspace_for_cm,
    ):
        instance = MagicMock()
        instance.__enter__.return_value = instance
        github_client_cls.return_value = instance
        workspace_for_cm.return_value.__enter__.return_value = workspace
        workspace_for_cm.return_value.__exit__.return_value = False
        return build_repository_context_for_snapshot(db, _FakeRepository(), _diff_snapshot())


def test_disabled_flag_skips_without_calling_github(tmp_path: Path) -> None:
    db = _db_with_no_existing_rows()

    with patch("app.context.service.get_settings", return_value=_settings(context_enabled=False)):
        result = build_repository_context_for_snapshot(db, _FakeRepository(), _diff_snapshot())

    assert result is None
    db.add.assert_not_called()


def test_existing_snapshot_is_reused(tmp_path: Path) -> None:
    db = MagicMock()
    existing = RepoContextSnapshot(id=9, repository_id=1, diff_snapshot_id=1)
    db.query.return_value.filter_by.return_value.one_or_none.return_value = existing

    result = _run(db, _settings(), tmp_path)

    assert result is existing
    db.add.assert_not_called()


def test_builds_profile_and_context_items_for_changed_symbol(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("context\ndef changed():\n    return 1\n")
    (tmp_path / "caller.py").write_text("from app import changed\n\nchanged()\n")
    db = _db_with_no_existing_rows()

    result = _run(db, _settings(), tmp_path)

    assert result is not None
    db.add.assert_called()
    persisted: RepoContextSnapshot = db.add.call_args[0][0]
    assert persisted.profile["languages"].get("Python") == 2
    kinds = {item["kind"] for item in persisted.context_items}
    assert "definition" in kinds


def _db_where_chunk_queries_return_empty() -> MagicMock:
    """Like `_db_with_no_existing_rows`, but also makes `db.query(...).
    filter_by(...)` iterable (empty), the shape `reindex_symbol_chunks`
    needs - so chunk indexing can run without hitting the generic
    MagicMock "not iterable" TypeError that `_db_with_no_existing_rows`
    triggers (and which the service is expected to catch and degrade on;
    see `test_chunk_indexing_failure_marks_snapshot_degraded`).
    """
    db = MagicMock()
    db.query.return_value.filter_by.return_value.one_or_none.return_value = None
    db.query.return_value.filter_by.return_value.__iter__.return_value = iter([])
    return db


def test_chunk_indexing_failure_marks_snapshot_degraded_but_still_persists_context(
    tmp_path: Path,
) -> None:
    (tmp_path / "app.py").write_text("context\ndef changed():\n    return 1\n")
    db = _db_where_chunk_queries_return_empty()

    with patch(
        "app.context.service.reindex_changed_file_chunks",
        side_effect=RuntimeError("indexing exploded"),
    ):
        result = _run(db, _settings(), tmp_path)

    assert result is not None
    persisted: RepoContextSnapshot = db.add.call_args[0][0]
    assert persisted.degraded is True
    # Degradation must not lose the lexical/structural context already
    # gathered - it's a fallback, not a failed review.
    kinds = {item["kind"] for item in persisted.context_items}
    assert "definition" in kinds


def test_successful_chunk_indexing_leaves_snapshot_not_degraded(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("context\ndef changed():\n    return 1\n")
    db = _db_where_chunk_queries_return_empty()

    result = _run(db, _settings(), tmp_path)

    assert result is not None
    persisted: RepoContextSnapshot = db.add.call_args[0][0]
    assert persisted.degraded is False


def test_embeddings_disabled_by_default_produces_no_semantic_items(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("context\ndef changed():\n    return 1\n")
    db = _db_where_chunk_queries_return_empty()

    result = _run(db, _settings(context_embeddings_enabled=False), tmp_path)

    assert result is not None
    persisted: RepoContextSnapshot = db.add.call_args[0][0]
    kinds = {item["kind"] for item in persisted.context_items}
    assert "semantic" not in kinds


def test_semantic_items_are_merged_when_embeddings_enabled(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("context\ndef changed():\n    return 1\n")
    (tmp_path / "other.py").write_text("def unrelated_but_similar():\n    return 2\n")
    db = _db_where_chunk_queries_return_empty()

    fake_provider = MagicMock()
    fake_provider.embed.return_value = MagicMock(vector=[0.1, 0.2], error=None)
    fake_candidate = MagicMock(
        path="other.py", symbol="unrelated_but_similar", start_line=1, end_line=2, distance=0.2
    )

    with (
        patch("app.context.service.build_embedding_provider", return_value=fake_provider),
        patch("app.context.service.semantic_candidates_for_symbol", return_value=[fake_candidate]),
    ):
        result = _run(
            db, _settings(context_embeddings_enabled=True, context_max_bytes=100_000), tmp_path
        )

    assert result is not None
    persisted: RepoContextSnapshot = db.add.call_args[0][0]
    kinds = {item["kind"] for item in persisted.context_items}
    assert "semantic" in kinds
    assert persisted.degraded is False
