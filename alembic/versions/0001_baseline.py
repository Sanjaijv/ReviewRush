"""baseline: empty schema, establishes Alembic version tracking

Revision ID: 0001
Revises:
Create Date: 2026-09-02

"""
from collections.abc import Sequence

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Intentionally empty. Domain models are introduced in later phases."""
    pass


def downgrade() -> None:
    pass
