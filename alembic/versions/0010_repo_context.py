"""Repository-aware context: repo_file_index, repo_context_snapshots, ai_findings.context_refs

Revision ID: 0010
Revises: 0009
Create Date: 2026-09-02

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "repo_file_index",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "repository_id", sa.Integer(), sa.ForeignKey("repositories.id"), nullable=False
        ),
        sa.Column("path", sa.String(length=1024), nullable=False),
        sa.Column("content_sha", sa.String(length=64), nullable=False),
        sa.Column("language", sa.String(length=32), nullable=False, server_default=""),
        sa.Column(
            "symbols",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
        sa.Column("last_seen_commit_sha", sa.String(length=40), nullable=False),
        sa.Column(
            "indexed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("repository_id", "path", name="uq_repo_file_index_repo_path"),
    )
    op.create_index("ix_repo_file_index_repository_id", "repo_file_index", ["repository_id"])

    op.create_table(
        "repo_context_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "repository_id", sa.Integer(), sa.ForeignKey("repositories.id"), nullable=False
        ),
        sa.Column(
            "diff_snapshot_id",
            sa.Integer(),
            sa.ForeignKey("diff_snapshots.id"),
            nullable=False,
        ),
        sa.Column(
            "profile", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"
        ),
        sa.Column(
            "guidance", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"
        ),
        sa.Column(
            "context_items",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
        sa.Column("truncated", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("total_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint(
            "diff_snapshot_id", name="uq_repo_context_snapshots_diff_snapshot_id"
        ),
    )
    op.create_index(
        "ix_repo_context_snapshots_repository_id", "repo_context_snapshots", ["repository_id"]
    )
    op.create_index(
        "ix_repo_context_snapshots_diff_snapshot_id",
        "repo_context_snapshots",
        ["diff_snapshot_id"],
    )

    op.add_column(
        "ai_findings",
        sa.Column(
            "context_refs",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
    )


def downgrade() -> None:
    op.drop_column("ai_findings", "context_refs")
    op.drop_index("ix_repo_context_snapshots_diff_snapshot_id", table_name="repo_context_snapshots")
    op.drop_index("ix_repo_context_snapshots_repository_id", table_name="repo_context_snapshots")
    op.drop_table("repo_context_snapshots")
    op.drop_index("ix_repo_file_index_repository_id", table_name="repo_file_index")
    op.drop_table("repo_file_index")
