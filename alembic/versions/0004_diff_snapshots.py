"""diff retrieval and normalization: diff_snapshots, changed_files

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-02

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "diff_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "repository_id", sa.Integer(), sa.ForeignKey("repositories.id"), nullable=False
        ),
        sa.Column("head_sha", sa.String(length=40), nullable=False),
        sa.Column("base_sha", sa.String(length=40), nullable=False),
        sa.Column("merge_base_sha", sa.String(length=40), nullable=True),
        sa.Column(
            "commits",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="complete"),
        sa.Column("truncated", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("file_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_additions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_deletions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_changed_lines", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_patch_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("repository_id", "head_sha", name="uq_diff_snapshots_repo_head_sha"),
    )
    op.create_index("ix_diff_snapshots_repository_id", "diff_snapshots", ["repository_id"])

    op.create_table(
        "changed_files",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "diff_snapshot_id",
            sa.Integer(),
            sa.ForeignKey("diff_snapshots.id"),
            nullable=False,
        ),
        sa.Column("old_path", sa.String(length=1024), nullable=True),
        sa.Column("new_path", sa.String(length=1024), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("additions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("deletions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("changes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_binary", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_submodule", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_generated", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("excluded_from_ai", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("patch", sa.Text(), nullable=True),
        sa.Column("patch_truncated", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("content_fetched", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_changed_files_diff_snapshot_id", "changed_files", ["diff_snapshot_id"])


def downgrade() -> None:
    op.drop_table("changed_files")
    op.drop_table("diff_snapshots")
