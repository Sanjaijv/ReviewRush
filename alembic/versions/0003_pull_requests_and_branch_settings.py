"""branch monitoring: pull_requests table, repository branch overrides

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-02

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("repositories", sa.Column("source_branch", sa.String(length=255), nullable=True))
    op.add_column("repositories", sa.Column("target_branch", sa.String(length=255), nullable=True))

    op.create_table(
        "pull_requests",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "repository_id", sa.Integer(), sa.ForeignKey("repositories.id"), nullable=False
        ),
        sa.Column("github_pr_number", sa.Integer(), nullable=False),
        sa.Column("head_branch", sa.String(length=255), nullable=False),
        sa.Column("base_branch", sa.String(length=255), nullable=False),
        sa.Column("head_sha", sa.String(length=40), nullable=False),
        sa.Column("base_sha", sa.String(length=40), nullable=True),
        sa.Column("state", sa.String(length=32), nullable=False, server_default="open"),
        sa.Column(
            "last_synced_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint(
            "repository_id", "github_pr_number", name="uq_pull_requests_repo_pr_number"
        ),
    )
    op.create_index("ix_pull_requests_repository_id", "pull_requests", ["repository_id"])


def downgrade() -> None:
    op.drop_table("pull_requests")
    op.drop_column("repositories", "target_branch")
    op.drop_column("repositories", "source_branch")
