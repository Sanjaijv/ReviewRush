"""deterministic analysis pipeline: tool_runs

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-02

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tool_runs",
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
        sa.Column("check_name", sa.String(length=128), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="completed"),
        sa.Column("conclusion", sa.String(length=32), nullable=False),
        sa.Column("required", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("exit_code", sa.Integer(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("summary", sa.String(length=2000), nullable=False, server_default=""),
        sa.Column(
            "annotations",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
        sa.Column("log_excerpt", sa.Text(), nullable=True),
        sa.Column("log_truncated", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint(
            "diff_snapshot_id", "check_name", name="uq_tool_runs_snapshot_check_name"
        ),
    )
    op.create_index("ix_tool_runs_repository_id", "tool_runs", ["repository_id"])
    op.create_index("ix_tool_runs_diff_snapshot_id", "tool_runs", ["diff_snapshot_id"])


def downgrade() -> None:
    op.drop_table("tool_runs")
