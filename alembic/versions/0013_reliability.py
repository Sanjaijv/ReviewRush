"""Reliability, observability, and production hardening: task_failures
dead-letter table.

Revision ID: 0013
Revises: 0012
Create Date: 2026-09-02

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "task_failures",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "repository_id", sa.Integer(), sa.ForeignKey("repositories.id"), nullable=True
        ),
        sa.Column(
            "diff_snapshot_id", sa.Integer(), sa.ForeignKey("diff_snapshots.id"), nullable=True
        ),
        sa.Column("task_name", sa.String(length=128), nullable=False),
        sa.Column("task_id", sa.String(length=64), nullable=False),
        sa.Column(
            "task_args",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("exception_type", sa.String(length=255), nullable=False),
        sa.Column("exception_message", sa.Text(), nullable=False),
        sa.Column("traceback", sa.Text(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_task_failures_repository_id", "task_failures", ["repository_id"])
    op.create_index("ix_task_failures_diff_snapshot_id", "task_failures", ["diff_snapshot_id"])
    op.create_index("ix_task_failures_task_name", "task_failures", ["task_name"])


def downgrade() -> None:
    op.drop_index("ix_task_failures_task_name", table_name="task_failures")
    op.drop_index("ix_task_failures_diff_snapshot_id", table_name="task_failures")
    op.drop_index("ix_task_failures_repository_id", table_name="task_failures")
    op.drop_table("task_failures")
