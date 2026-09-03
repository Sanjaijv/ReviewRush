"""Safe auto-approval and auto-merge: merge_attempts

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-02

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "merge_attempts",
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
            "pull_request_id", sa.Integer(), sa.ForeignKey("pull_requests.id"), nullable=True
        ),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column(
            "reasons", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"
        ),
        sa.Column("github_response", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_merge_attempts_repository_id", "merge_attempts", ["repository_id"])
    op.create_index("ix_merge_attempts_diff_snapshot_id", "merge_attempts", ["diff_snapshot_id"])


def downgrade() -> None:
    op.drop_index("ix_merge_attempts_diff_snapshot_id", table_name="merge_attempts")
    op.drop_index("ix_merge_attempts_repository_id", table_name="merge_attempts")
    op.drop_table("merge_attempts")
