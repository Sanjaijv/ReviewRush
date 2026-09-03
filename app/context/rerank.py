"""Combine lexical/structural and semantic retrieval candidates into one
ranked list (Phase 11), and query pgvector for semantic candidates.

Every semantic query is filtered by `repository_id` - retrieval must never
cross repository/customer boundaries, per the roadmap's Phase 11 acceptance
criteria - and every candidate's actual text is still read live from the
caller-supplied workspace checkout, never from the stored chunk row, so
semantic retrieval carries the same no-stale-cross-commit-text guarantee as
lexical retrieval (app/context/retrieval.py).
"""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.context.retrieval import ContextItem, snippet_for_range
from app.models import RepoSymbolChunk

_KIND_WEIGHT: dict[str, float] = {
    "definition": 100.0,
    "test": 60.0,
    "reference": 50.0,
    "semantic": 30.0,
    "config": 20.0,
    "guidance": 10.0,
}


@dataclass
class SemanticCandidate:
    path: str
    symbol: str
    start_line: int
    end_line: int
    distance: float


def _read_file(path: Path, max_bytes: int) -> str | None:
    try:
        if path.stat().st_size > max_bytes:
            return None
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def semantic_candidates_for_symbol(
    db: Any,
    repository_id: int,
    query_embedding: list[float],
    exclude_path: str,
    limit: int,
) -> list[SemanticCandidate]:
    """Nearest-neighbor lookup by cosine distance, always scoped to one
    repository. Returns metadata only (path/symbol/line range) - never
    the persisted chunk's embedding or any code text.
    """
    distance_expr = RepoSymbolChunk.embedding.cosine_distance(query_embedding)
    rows = (
        db.query(RepoSymbolChunk, distance_expr.label("distance"))
        .filter(
            RepoSymbolChunk.repository_id == repository_id,
            RepoSymbolChunk.embedding.isnot(None),
            RepoSymbolChunk.path != exclude_path,
        )
        .order_by(distance_expr)
        .limit(limit)
        .all()
    )
    return [
        SemanticCandidate(
            path=row.path,
            symbol=row.symbol,
            start_line=row.start_line,
            end_line=row.end_line,
            distance=float(distance) if distance is not None else 1.0,
        )
        for row, distance in rows
    ]


def build_semantic_context_items(
    workspace_root: Path,
    candidates: list[SemanticCandidate],
    origin_symbol: str,
    origin_path: str,
    max_file_bytes: int,
) -> list[ContextItem]:
    items: list[ContextItem] = []
    for candidate in candidates:
        content = _read_file(workspace_root / candidate.path, max_file_bytes)
        if content is None:
            continue
        content_lines = content.splitlines()
        snippet, lo, hi = snippet_for_range(content_lines, candidate.start_line, candidate.end_line)
        similarity = max(0.0, 1.0 - candidate.distance)
        items.append(
            ContextItem(
                id="",
                path=candidate.path,
                kind="semantic",
                symbol=candidate.symbol,
                start_line=lo,
                end_line=hi,
                snippet=snippet,
                reason=(
                    f"semantically related to '{origin_symbol}' "
                    f"(changed in {origin_path}), similarity {similarity:.2f}"
                ),
            )
        )
    return items


def rerank(
    items: list[ContextItem],
    changed_paths: set[str],
    changed_symbol_names: set[str],
    fresh_paths: set[str],
) -> list[ContextItem]:
    """Order candidates by kind, path relevance, recency, and query
    specificity, highest-relevance first. `apply_budget` then keeps items in
    this order until the byte budget runs out, instead of the size-naive
    "smallest first" ordering used before Phase 11.
    """
    changed_dirs = {os.path.dirname(path) for path in changed_paths}

    def score(item: ContextItem) -> float:
        value = _KIND_WEIGHT.get(item.kind, 0.0)
        if os.path.dirname(item.path) in changed_dirs:
            value += 15.0
        if item.path in fresh_paths:
            value += 5.0
        if item.symbol in changed_symbol_names:
            value += 8.0
        return value

    return sorted(items, key=score, reverse=True)
