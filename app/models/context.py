from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

# Fixed at the schema level (the pgvector column width can't vary per row),
# so it must match `Settings.context_embeddings_dimensions`. Changing the
# configured embeddings model to one with a different output width requires
# a migration to resize this column - see app/context/embeddings.py.
EMBEDDING_DIMENSIONS = 768


class RepoFileIndex(Base):
    """Persistent, incrementally-maintained symbol index for one file in a
    repository, keyed by path rather than commit.

    Unlike DiffSnapshot/ToolRun/AIReview (immutable per head_sha), this row
    is deliberately mutable and long-lived: it is only re-parsed when a
    review touches that path and its content actually changed (`content_sha`
    differs), so that "re-index only changed files after the initial index"
    holds even across many unrelated reviews. `symbols` stores only symbol
    *metadata* (name, kind, line range) - never code text - so a caller
    reading this row can never surface stale cross-commit source text; the
    actual snippet text for a review is always re-read from that review's
    own workspace checkout.
    """

    __tablename__ = "repo_file_index"
    __table_args__ = (
        UniqueConstraint("repository_id", "path", name="uq_repo_file_index_repo_path"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    repository_id: Mapped[int] = mapped_column(ForeignKey("repositories.id"), index=True)

    path: Mapped[str] = mapped_column(String(1024))
    content_sha: Mapped[str] = mapped_column(String(64))
    language: Mapped[str] = mapped_column(String(32), default="")
    symbols: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)

    last_seen_commit_sha: Mapped[str] = mapped_column(String(40))
    indexed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class RepoContextSnapshot(Base):
    """One immutable repository-context retrieval result for a DiffSnapshot's
    head_sha, mirroring AIReview's idempotency: a rebuild request for an
    already-indexed head_sha reuses the existing row rather than re-running
    retrieval, and a row built for one commit is never reused for another.

    `context_items` entries each carry their own id (referenced by
    `AIFinding.context_refs`), path, kind (definition/reference/test/config/
    guidance), line range, snippet text, and a `reason` describing why the
    item was retrieved - the provenance the Phase 10 acceptance criteria
    require.
    """

    __tablename__ = "repo_context_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "diff_snapshot_id", name="uq_repo_context_snapshots_diff_snapshot_id"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    repository_id: Mapped[int] = mapped_column(ForeignKey("repositories.id"), index=True)
    diff_snapshot_id: Mapped[int] = mapped_column(
        ForeignKey("diff_snapshots.id"), index=True
    )

    profile: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    guidance: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    context_items: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)

    truncated: Mapped[bool] = mapped_column(Boolean, default=False)
    total_bytes: Mapped[int] = mapped_column(Integer, default=0)
    # True when chunk re-indexing or semantic retrieval hit an unexpected
    # error (not merely a byte-budget truncation) and this snapshot's
    # context items reflect a lexical/structural-only fallback - the
    # documented Phase 11 "degraded mode" rather than a failed review.
    degraded: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RepoSymbolChunk(Base):
    """One symbol-level retrieval chunk for semantic + relationship search,
    incrementally maintained like `RepoFileIndex` but at chunk (not file)
    granularity, since that's the natural unit for both a pgvector nearest-
    neighbor query and symbol-graph re-ranking.

    Like `RepoFileIndex`, this never stores chunk text - only an `embedding`
    vector derived from it plus lexical `relationships` (other symbol names
    referenced within the chunk). A stored vector cannot be turned back into
    source text, so persisting it across commits doesn't reintroduce the
    stale-cross-commit-text risk `RepoFileIndex` was designed to avoid; the
    snippet a review actually sees is still always re-read live from that
    review's own workspace checkout (see app/context/retrieval.py).
    """

    __tablename__ = "repo_symbol_chunks"
    __table_args__ = (
        UniqueConstraint(
            "repository_id", "path", "symbol", "start_line",
            name="uq_repo_symbol_chunks_repo_path_symbol_start",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    repository_id: Mapped[int] = mapped_column(ForeignKey("repositories.id"), index=True)

    path: Mapped[str] = mapped_column(String(1024))
    symbol: Mapped[str] = mapped_column(String(256))
    kind: Mapped[str] = mapped_column(String(32))
    start_line: Mapped[int] = mapped_column(Integer)
    end_line: Mapped[int] = mapped_column(Integer)

    content_sha: Mapped[str] = mapped_column(String(64))
    relationships: Mapped[list[str]] = mapped_column(JSONB, default=list)

    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(EMBEDDING_DIMENSIONS), nullable=True
    )
    embedding_model: Mapped[str | None] = mapped_column(String(128), nullable=True)

    last_seen_commit_sha: Mapped[str] = mapped_column(String(40))
    indexed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
