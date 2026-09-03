from pathlib import Path
from unittest.mock import MagicMock

from app.context.retrieval import (
    ContextItem,
    apply_budget,
    build_context_items_for_symbol,
    find_config_items,
    iter_source_files,
    reindex_changed_files,
)
from app.context.symbols import Symbol
from app.models import ChangedFile, RepoFileIndex

_PATCH = "@@ -1,2 +1,3 @@\n context\n+def changed():\n+    return 1"


def _db_with_no_existing_index() -> MagicMock:
    db = MagicMock()
    db.query.return_value.filter_by.return_value.one_or_none.return_value = None
    return db


def test_reindex_changed_files_upserts_index_and_returns_changed_symbols(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("context\ndef changed():\n    return 1\n")
    changed_file = ChangedFile(
        new_path="app.py", old_path="app.py", status="modified", patch=_PATCH
    )
    db = _db_with_no_existing_index()

    result = reindex_changed_files(
        db=db,
        repository_id=1,
        workspace_root=tmp_path,
        changed_files=[changed_file],
        head_sha="sha1",
        max_file_bytes=500_000,
        max_symbols_per_file=50,
    )

    assert "app.py" in result
    assert any(s.name == "changed" for s in result["app.py"])
    db.add.assert_called_once()
    added_row: RepoFileIndex = db.add.call_args[0][0]
    assert added_row.last_seen_commit_sha == "sha1"
    assert added_row.language == "python"


def test_reindex_skips_unchanged_files_not_in_diff(tmp_path: Path) -> None:
    (tmp_path / "untouched.py").write_text("def untouched():\n    pass\n")
    db = _db_with_no_existing_index()

    result = reindex_changed_files(
        db=db,
        repository_id=1,
        workspace_root=tmp_path,
        changed_files=[],
        head_sha="sha1",
        max_file_bytes=500_000,
        max_symbols_per_file=50,
    )

    assert result == {}
    db.add.assert_not_called()


def test_reindex_removed_file_deletes_index_row(tmp_path: Path) -> None:
    changed_file = ChangedFile(new_path=None, old_path="gone.py", status="removed")
    db = MagicMock()

    reindex_changed_files(
        db=db,
        repository_id=1,
        workspace_root=tmp_path,
        changed_files=[changed_file],
        head_sha="sha1",
        max_file_bytes=500_000,
        max_symbols_per_file=50,
    )

    db.query.return_value.filter_by.assert_called_with(repository_id=1, path="gone.py")
    db.query.return_value.filter_by.return_value.delete.assert_called_once()


def test_build_context_items_includes_definition_and_reference(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text(
        "def shared():\n    return 1\n\n\ndef changed():\n    return shared()\n"
    )
    (tmp_path / "caller.py").write_text("from app import changed\n\nchanged()\n")

    symbol = Symbol(name="changed", kind="function", start_line=5, end_line=6)
    source_files = iter_source_files(tmp_path, max_files_scanned=1000)

    items = build_context_items_for_symbol(
        tmp_path, "app.py", symbol, source_files, max_items_per_symbol=5, max_file_bytes=500_000
    )

    kinds = {item.kind for item in items}
    assert "definition" in kinds
    assert "reference" in kinds
    reference = next(i for i in items if i.kind == "reference")
    assert reference.path == "caller.py"


def test_find_config_items_matches_schema_and_config_files(tmp_path: Path) -> None:
    (tmp_path / "models").mkdir()
    (tmp_path / "models" / "user.py").write_text("class User:\n    pass\n")
    (tmp_path / "models" / "schema.py").write_text("USER_SCHEMA = {}\n")
    (tmp_path / "models" / "unrelated.py").write_text("x = 1\n")

    items = find_config_items(
        tmp_path, "models/user.py", max_items=5, max_file_bytes=500_000
    )

    assert len(items) == 1
    assert items[0].path == "models/schema.py"
    assert items[0].kind == "config"


def test_apply_budget_keeps_caller_order_and_assigns_ids() -> None:
    """Phase 11: apply_budget keeps items in the order the caller ranked
    them (highest-relevance first, per app/context/rerank.py) rather than
    resorting by size - an oversized item is skipped in place so smaller,
    lower-priority items behind it still get a chance to fit.
    """
    small = ContextItem(
        id="", path="a.py", kind="reference", symbol="f", start_line=1, end_line=1,
        snippet="x", reason="r",
    )
    big = ContextItem(
        id="", path="b.py", kind="reference", symbol="f", start_line=1, end_line=1,
        snippet="y" * 1000, reason="r",
    )

    kept, truncated, used_bytes = apply_budget([big, small], max_bytes=10)

    assert truncated is True
    assert [item.path for item in kept] == ["a.py"]
    assert kept[0].id == "ctx-1"
    assert used_bytes == 1


def test_apply_budget_preserves_priority_order_when_everything_fits() -> None:
    first = ContextItem(
        id="", path="a.py", kind="definition", symbol="f", start_line=1, end_line=1,
        snippet="a", reason="r",
    )
    second = ContextItem(
        id="", path="b.py", kind="semantic", symbol="g", start_line=1, end_line=1,
        snippet="bb", reason="r",
    )

    kept, truncated, used_bytes = apply_budget([first, second], max_bytes=100)

    assert truncated is False
    assert [item.path for item in kept] == ["a.py", "b.py"]
    assert used_bytes == 3
