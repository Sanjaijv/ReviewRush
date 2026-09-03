"""Multi-tenant SaaS readiness (Phase 17): organizations, organization_members.

Backfills exactly one Organization per existing Installation, matching the
1:1 Installation<->Organization boundary `app.tenancy.provisioning` enforces
going forward, so no pre-existing installation is left without a tenant.

Revision ID: 0017
Revises: 0016
Create Date: 2026-09-03

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "organizations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "installation_id", sa.Integer(), sa.ForeignKey("installations.id"), nullable=False
        ),
        sa.Column("slug", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("plan", sa.String(length=32), nullable=False, server_default="free"),
        sa.Column("max_ai_reviews_per_day", sa.Integer(), nullable=True),
        sa.Column("max_repositories", sa.Integer(), nullable=True),
        sa.Column("region", sa.String(length=32), nullable=False, server_default="us"),
        sa.Column("retention_days_default", sa.Integer(), nullable=True),
        sa.Column("ai_provider_override", sa.String(length=64), nullable=True),
        sa.Column("ai_model_override", sa.String(length=128), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("installation_id", name="uq_organizations_installation_id"),
        sa.UniqueConstraint("slug", name="uq_organizations_slug"),
    )
    op.create_index("ix_organizations_installation_id", "organizations", ["installation_id"])

    op.create_table(
        "organization_members",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False
        ),
        sa.Column("github_user_id", sa.Integer(), nullable=False),
        sa.Column("login", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False, server_default="member"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint(
            "organization_id", "github_user_id", name="uq_org_members_org_user"
        ),
    )
    op.create_index(
        "ix_organization_members_organization_id", "organization_members", ["organization_id"]
    )
    op.create_index(
        "ix_organization_members_github_user_id", "organization_members", ["github_user_id"]
    )

    # Backfill: one Organization per existing Installation. Slug is the
    # lowercased account_login, de-duplicated with the installation id if
    # a collision would otherwise violate the unique constraint (two
    # installations can't share an account_login, but this keeps the
    # migration safe against any pre-existing dirty data).
    connection = op.get_bind()
    installations = connection.execute(
        sa.text("SELECT id, account_login FROM installations")
    ).fetchall()
    seen_slugs: set[str] = set()
    for installation_id, account_login in installations:
        base_slug = (account_login or f"installation-{installation_id}").strip().lower() or (
            f"installation-{installation_id}"
        )
        slug = base_slug
        if slug in seen_slugs:
            slug = f"{base_slug}-{installation_id}"
        seen_slugs.add(slug)
        connection.execute(
            sa.text(
                "INSERT INTO organizations (installation_id, slug, name, plan, region) "
                "VALUES (:installation_id, :slug, :name, 'free', 'us')"
            ),
            {
                "installation_id": installation_id,
                "slug": slug,
                "name": account_login or slug,
            },
        )


def downgrade() -> None:
    op.drop_index("ix_organization_members_github_user_id", table_name="organization_members")
    op.drop_index("ix_organization_members_organization_id", table_name="organization_members")
    op.drop_table("organization_members")
    op.drop_index("ix_organizations_installation_id", table_name="organizations")
    op.drop_table("organizations")
