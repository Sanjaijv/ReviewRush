"""Add diff_snapshots.pull_request_id, a stable link to the PR a push was
synced against at the time its snapshot was created - fixes a race where a
slow background stage (autofix, checks) looked up the PR by matching
diff_snapshot.head_sha against the mutable pull_requests.head_sha, which a
newer push can move on before the slow stage finishes.

Revision ID: 0020
Revises: 0019
Create Date: 2026-09-05

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "diff_snapshots",
        sa.Column(
            "pull_request_id", sa.Integer(), sa.ForeignKey("pull_requests.id"), nullable=True
        ),
    )
    op.create_index(
        "ix_diff_snapshots_pull_request_id", "diff_snapshots", ["pull_request_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_diff_snapshots_pull_request_id", table_name="diff_snapshots")
    op.drop_column("diff_snapshots", "pull_request_id")
