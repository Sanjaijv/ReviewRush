"""Policy and risk decision engine: policy_decisions

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-02

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "policy_decisions",
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
        sa.Column("policy_version", sa.String(length=32), nullable=False),
        sa.Column("decision", sa.String(length=32), nullable=False),
        sa.Column("risk", sa.String(length=32), nullable=False),
        sa.Column(
            "reasons", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"
        ),
        sa.Column(
            "evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("diff_snapshot_id", name="uq_policy_decisions_diff_snapshot_id"),
    )
    op.create_index("ix_policy_decisions_repository_id", "policy_decisions", ["repository_id"])
    op.create_index(
        "ix_policy_decisions_diff_snapshot_id", "policy_decisions", ["diff_snapshot_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_policy_decisions_diff_snapshot_id", table_name="policy_decisions")
    op.drop_index("ix_policy_decisions_repository_id", table_name="policy_decisions")
    op.drop_table("policy_decisions")
