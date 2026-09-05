"""Add auto_fix_attempts.trigger/commit_sha/actor_login, and the "committed"/
"stale_target" statuses, for on-demand fixes triggered by a human checking
the "Apply this fix" checkbox rendered on a finding automatic auto-fix would
never attempt (security findings, or above the repo's severity ceiling).

Revision ID: 0021
Revises: 0020
Create Date: 2026-09-05

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "auto_fix_attempts",
        sa.Column("trigger", sa.String(length=16), nullable=False, server_default="automatic"),
    )
    op.add_column(
        "auto_fix_attempts", sa.Column("commit_sha", sa.String(length=40), nullable=True)
    )
    op.add_column(
        "auto_fix_attempts", sa.Column("actor_login", sa.String(length=255), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("auto_fix_attempts", "actor_login")
    op.drop_column("auto_fix_attempts", "commit_sha")
    op.drop_column("auto_fix_attempts", "trigger")
