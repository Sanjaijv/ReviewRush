"""AI auto-fix: auto_fix_attempts.

Records one attempt per AIFinding to generate, verify, and open a fix-PR for
a low-severity, non-security finding - append-only, unique on ai_finding_id
so an already-attempted finding is never re-fixed (and never re-pushed) by a
later rerun.

Revision ID: 0018
Revises: 0017
Create Date: 2026-09-04

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "auto_fix_attempts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "repository_id", sa.Integer(), sa.ForeignKey("repositories.id"), nullable=False
        ),
        sa.Column(
            "diff_snapshot_id", sa.Integer(), sa.ForeignKey("diff_snapshots.id"), nullable=False
        ),
        sa.Column(
            "ai_finding_id", sa.Integer(), sa.ForeignKey("ai_findings.id"), nullable=False
        ),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("branch_name", sa.String(length=255), nullable=True),
        sa.Column("pull_request_number", sa.BigInteger(), nullable=True),
        sa.Column("pull_request_url", sa.String(length=1024), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("ai_finding_id", name="uq_auto_fix_attempts_ai_finding_id"),
    )
    op.create_index("ix_auto_fix_attempts_repository_id", "auto_fix_attempts", ["repository_id"])
    op.create_index(
        "ix_auto_fix_attempts_diff_snapshot_id", "auto_fix_attempts", ["diff_snapshot_id"]
    )
    op.create_index(
        "ix_auto_fix_attempts_ai_finding_id", "auto_fix_attempts", ["ai_finding_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_auto_fix_attempts_ai_finding_id", table_name="auto_fix_attempts")
    op.drop_index("ix_auto_fix_attempts_diff_snapshot_id", table_name="auto_fix_attempts")
    op.drop_index("ix_auto_fix_attempts_repository_id", table_name="auto_fix_attempts")
    op.drop_table("auto_fix_attempts")
