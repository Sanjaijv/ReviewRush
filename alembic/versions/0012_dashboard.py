"""Dashboard, configuration, and auditability: audit_events,
repository_config_versions, repository disconnect/retention columns

Revision ID: 0012
Revises: 0011
Create Date: 2026-09-02

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "audit_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "repository_id", sa.Integer(), sa.ForeignKey("repositories.id"), nullable=True
        ),
        sa.Column("actor_type", sa.String(length=16), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), nullable=True),
        sa.Column("actor_login", sa.String(length=255), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("target_type", sa.String(length=64), nullable=False),
        sa.Column("target_id", sa.String(length=64), nullable=True),
        sa.Column(
            "event_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_audit_events_repository_id", "audit_events", ["repository_id"])
    op.create_index("ix_audit_events_action", "audit_events", ["action"])

    op.create_table(
        "repository_config_versions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "repository_id", sa.Integer(), sa.ForeignKey("repositories.id"), nullable=False
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("config", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), nullable=False),
        sa.Column("actor_login", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index(
        "ix_repository_config_versions_repository_id",
        "repository_config_versions",
        ["repository_id"],
    )
    op.create_unique_constraint(
        "uq_repository_config_versions_repo_version",
        "repository_config_versions",
        ["repository_id", "version"],
    )

    op.add_column(
        "repositories", sa.Column("disconnected_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "repositories", sa.Column("disconnected_by", sa.String(length=255), nullable=True)
    )
    op.add_column("repositories", sa.Column("retention_days", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("repositories", "retention_days")
    op.drop_column("repositories", "disconnected_by")
    op.drop_column("repositories", "disconnected_at")

    op.drop_constraint(
        "uq_repository_config_versions_repo_version",
        "repository_config_versions",
        type_="unique",
    )
    op.drop_index(
        "ix_repository_config_versions_repository_id", table_name="repository_config_versions"
    )
    op.drop_table("repository_config_versions")

    op.drop_index("ix_audit_events_action", table_name="audit_events")
    op.drop_index("ix_audit_events_repository_id", table_name="audit_events")
    op.drop_table("audit_events")
