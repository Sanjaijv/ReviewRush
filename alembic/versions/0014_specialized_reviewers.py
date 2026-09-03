"""Specialized reviewers and consensus: specialized_reviews audit table plus
ai_findings.contributing_reviewers provenance column.

Revision ID: 0014
Revises: 0013
Create Date: 2026-09-03

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "specialized_reviews",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "ai_review_id", sa.Integer(), sa.ForeignKey("ai_reviews.id"), nullable=False
        ),
        sa.Column(
            "repository_id", sa.Integer(), sa.ForeignKey("repositories.id"), nullable=False
        ),
        sa.Column("reviewer", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("decision", sa.String(length=32), nullable=True),
        sa.Column("risk", sa.String(length=32), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completion_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("latency_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index(
        "ix_specialized_reviews_ai_review_id", "specialized_reviews", ["ai_review_id"]
    )
    op.create_index(
        "ix_specialized_reviews_repository_id", "specialized_reviews", ["repository_id"]
    )

    op.add_column(
        "ai_findings",
        sa.Column(
            "contributing_reviewers",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default='["general"]',
        ),
    )


def downgrade() -> None:
    op.drop_column("ai_findings", "contributing_reviewers")
    op.drop_index("ix_specialized_reviews_repository_id", table_name="specialized_reviews")
    op.drop_index("ix_specialized_reviews_ai_review_id", table_name="specialized_reviews")
    op.drop_table("specialized_reviews")
