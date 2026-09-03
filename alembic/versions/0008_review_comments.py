"""GitHub checks, summaries, and inline comments: review_comments,
diff_snapshots.github_check_run_id

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-02

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "diff_snapshots", sa.Column("github_check_run_id", sa.BigInteger(), nullable=True)
    )

    op.create_table(
        "review_comments",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "repository_id", sa.Integer(), sa.ForeignKey("repositories.id"), nullable=False
        ),
        sa.Column(
            "pull_request_id", sa.Integer(), sa.ForeignKey("pull_requests.id"), nullable=False
        ),
        sa.Column(
            "diff_snapshot_id",
            sa.Integer(),
            sa.ForeignKey("diff_snapshots.id"),
            nullable=False,
        ),
        sa.Column("ai_finding_id", sa.Integer(), sa.ForeignKey("ai_findings.id"), nullable=True),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("github_comment_id", sa.BigInteger(), nullable=False),
        sa.Column("path", sa.String(length=1024), nullable=True),
        sa.Column("line", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="posted"),
        sa.Column("head_sha", sa.String(length=40), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint(
            "pull_request_id", "kind", "fingerprint", name="uq_review_comments_pr_kind_fingerprint"
        ),
    )
    op.create_index("ix_review_comments_repository_id", "review_comments", ["repository_id"])
    op.create_index("ix_review_comments_pull_request_id", "review_comments", ["pull_request_id"])
    op.create_index("ix_review_comments_diff_snapshot_id", "review_comments", ["diff_snapshot_id"])


def downgrade() -> None:
    op.drop_index("ix_review_comments_diff_snapshot_id", table_name="review_comments")
    op.drop_index("ix_review_comments_pull_request_id", table_name="review_comments")
    op.drop_index("ix_review_comments_repository_id", table_name="review_comments")
    op.drop_table("review_comments")

    op.drop_column("diff_snapshots", "github_check_run_id")
