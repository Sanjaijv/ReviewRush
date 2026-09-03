from pathlib import Path
from unittest.mock import MagicMock

from app.context.rerank import (
    SemanticCandidate,
    build_semantic_context_items,
    rerank,
    semantic_candidates_for_symbol,
)
from app.context.retrieval import ContextItem


def _item(kind: str, path: str, symbol: str | None = None) -> ContextItem:
    return ContextItem(
        id="", path=path, kind=kind, symbol=symbol, start_line=1, end_line=1,
        snippet="x", reason="r",
    )


def test_rerank_orders_definition_before_semantic_before_config() -> None:
    items = [
        _item("config", "models/schema.py"),
        _item("semantic", "other/module.py"),
        _item("definition", "app.py"),
    ]

    ordered = rerank(
        items, changed_paths={"app.py"}, changed_symbol_names=set(), fresh_paths=set()
    )

    assert [item.kind for item in ordered] == ["definition", "semantic", "config"]


def test_rerank_boosts_same_directory_reference_above_a_far_one() -> None:
    same_dir_reference = _item("reference", "app/helpers.py", symbol="other")
    far_reference = _item("reference", "unrelated/thing.py", symbol="other")

    ordered = rerank(
        [far_reference, same_dir_reference],
        changed_paths={"app/main.py"},
        changed_symbol_names=set(),
        fresh_paths=set(),
    )

    assert ordered[0] is same_dir_reference


def test_rerank_boosts_exact_symbol_match_within_the_same_kind() -> None:
    exact_symbol_semantic = _item("semantic", "unrelated/thing.py", symbol="changed")
    other_symbol_semantic = _item("semantic", "unrelated/thing2.py", symbol="other")

    ordered = rerank(
        [other_symbol_semantic, exact_symbol_semantic],
        changed_paths={"app/main.py"},
        changed_symbol_names={"changed"},
        fresh_paths=set(),
    )

    assert ordered[0] is exact_symbol_semantic


def test_semantic_candidates_for_symbol_filters_by_repository_and_excludes_own_path() -> None:
    db = MagicMock()
    fake_row = MagicMock(path="other.py", symbol="helper", start_line=3, end_line=5)
    query = db.query.return_value
    query.filter.return_value.order_by.return_value.limit.return_value.all.return_value = [
        (fake_row, 0.25)
    ]

    candidates = semantic_candidates_for_symbol(
        db, repository_id=1, query_embedding=[0.1, 0.2], exclude_path="app.py", limit=8
    )

    assert candidates == [
        SemanticCandidate(path="other.py", symbol="helper", start_line=3, end_line=5, distance=0.25)
    ]
    filter_args = query.filter.call_args[0]
    # repository_id and exclude-own-path filters must always be present -
    # retrieval must never cross repository boundaries.
    assert any("repository_id" in str(arg) for arg in filter_args)
    assert any("path" in str(arg) for arg in filter_args)


def test_build_semantic_context_items_reads_snippet_live_from_workspace(tmp_path: Path) -> None:
    (tmp_path / "other.py").write_text("def helper():\n    return 1\n")
    candidate = SemanticCandidate(
        path="other.py", symbol="helper", start_line=1, end_line=2, distance=0.1
    )

    items = build_semantic_context_items(
        tmp_path, [candidate], origin_symbol="changed", origin_path="app.py", max_file_bytes=500_000
    )

    assert len(items) == 1
    assert items[0].kind == "semantic"
    assert "def helper" in items[0].snippet
    assert "changed" in items[0].reason
