"""Add review_comments.github_node_id, needed to collapse an outdated inline
comment via the GraphQL minimizeComment mutation (the REST API has no
equivalent - it can only edit a comment's body, not hide/collapse it).

Revision ID: 0017
Revises: 0016
Create Date: 2026-09-05

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "review_comments", sa.Column("github_node_id", sa.String(length=128), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("review_comments", "github_node_id")
