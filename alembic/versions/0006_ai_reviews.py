"""AI reviewer MVP: ai_reviews, ai_findings

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-02

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ai_reviews",
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
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("decision", sa.String(length=32), nullable=True),
        sa.Column("risk", sa.String(length=32), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("provider", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("model", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completion_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("latency_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("diff_snapshot_id", name="uq_ai_reviews_diff_snapshot_id"),
    )
    op.create_index("ix_ai_reviews_repository_id", "ai_reviews", ["repository_id"])
    op.create_index("ix_ai_reviews_diff_snapshot_id", "ai_reviews", ["diff_snapshot_id"])

    op.create_table(
        "ai_findings",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("ai_review_id", sa.Integer(), sa.ForeignKey("ai_reviews.id"), nullable=False),
        sa.Column(
            "repository_id", sa.Integer(), sa.ForeignKey("repositories.id"), nullable=False
        ),
        sa.Column("file", sa.String(length=1024), nullable=False),
        sa.Column("start_line", sa.Integer(), nullable=False),
        sa.Column("end_line", sa.Integer(), nullable=False),
        sa.Column("severity", sa.String(length=32), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("evidence", sa.Text(), nullable=False),
        sa.Column("recommendation", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_ai_findings_ai_review_id", "ai_findings", ["ai_review_id"])
    op.create_index("ix_ai_findings_repository_id", "ai_findings", ["repository_id"])


def downgrade() -> None:
    op.drop_index("ix_ai_findings_repository_id", table_name="ai_findings")
    op.drop_index("ix_ai_findings_ai_review_id", table_name="ai_findings")
    op.drop_table("ai_findings")

    op.drop_index("ix_ai_reviews_diff_snapshot_id", table_name="ai_reviews")
    op.drop_index("ix_ai_reviews_repository_id", table_name="ai_reviews")
    op.drop_table("ai_reviews")
