"""RAG symbol chunks: repo_symbol_chunks (pgvector), repo_context_snapshots.degraded

Revision ID: 0011
Revises: 0010
Create Date: 2026-09-02

"""

from collections.abc import Sequence

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Must match app.models.context.EMBEDDING_DIMENSIONS / the default
# context_embeddings_dimensions setting (nomic-embed-text's output width).
EMBEDDING_DIMENSIONS = 768


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "repo_symbol_chunks",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "repository_id", sa.Integer(), sa.ForeignKey("repositories.id"), nullable=False
        ),
        sa.Column("path", sa.String(length=1024), nullable=False),
        sa.Column("symbol", sa.String(length=256), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("start_line", sa.Integer(), nullable=False),
        sa.Column("end_line", sa.Integer(), nullable=False),
        sa.Column("content_sha", sa.String(length=64), nullable=False),
        sa.Column(
            "relationships",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
        sa.Column("embedding", Vector(EMBEDDING_DIMENSIONS), nullable=True),
        sa.Column("embedding_model", sa.String(length=128), nullable=True),
        sa.Column("last_seen_commit_sha", sa.String(length=40), nullable=False),
        sa.Column(
            "indexed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint(
            "repository_id", "path", "symbol", "start_line",
            name="uq_repo_symbol_chunks_repo_path_symbol_start",
        ),
    )
    op.create_index("ix_repo_symbol_chunks_repository_id", "repo_symbol_chunks", ["repository_id"])
    # HNSW needs no training data (unlike IVFFlat), so it's safe to create
    # against an empty table at migration time.
    op.execute(
        "CREATE INDEX ix_repo_symbol_chunks_embedding_cosine "
        "ON repo_symbol_chunks USING hnsw (embedding vector_cosine_ops)"
    )

    op.add_column(
        "repo_context_snapshots",
        sa.Column("degraded", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("repo_context_snapshots", "degraded")
    op.execute("DROP INDEX IF EXISTS ix_repo_symbol_chunks_embedding_cosine")
    op.drop_index("ix_repo_symbol_chunks_repository_id", table_name="repo_symbol_chunks")
    op.drop_table("repo_symbol_chunks")
