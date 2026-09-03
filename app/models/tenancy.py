from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

if TYPE_CHECKING:
    from app.models.github import Installation


class Organization(Base):
    """The billing/RBAC tenant boundary for one GitHub App Installation
    (Phase 17).

    One Organization per Installation (auto-created in
    `app.tenancy.provisioning` right after the Installation row is first
    created) - this mirrors GitHub's own access boundary exactly rather than
    inventing a cross-installation grouping we have no reliable signal to
    verify, so every isolation check that already works at the Installation
    level (dashboard OAuth, `get_authorized_repository`) also holds at the
    Organization level for free. `plan` selects the usage-limit defaults in
    `app.tenancy.plans.PLAN_DEFAULTS`; `max_ai_reviews_per_day` /
    `max_repositories` are explicit per-organization overrides of those
    defaults and are null unless an admin has set one. `ai_provider_override`
    / `ai_model_override` let an organization pin its own reviewer
    provider/model instead of the global `Settings.ai_provider` /
    `Settings.ai_model` - null means "use the global default".
    """

    __tablename__ = "organizations"
    __table_args__ = (UniqueConstraint("installation_id", name="uq_organizations_installation_id"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    installation_id: Mapped[int] = mapped_column(ForeignKey("installations.id"), index=True)

    slug: Mapped[str] = mapped_column(String(255), unique=True)
    name: Mapped[str] = mapped_column(String(255))

    plan: Mapped[str] = mapped_column(String(32), default="free")
    max_ai_reviews_per_day: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_repositories: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Informational only in this release (no multi-region infrastructure) -
    # recorded so a future region-pinned deployment has somewhere to read an
    # organization's declared residency requirement from.
    region: Mapped[str] = mapped_column(String(32), default="us")
    # Overrides `Settings.dashboard_default_retention_days` for this
    # organization's repositories when set; null defers to the global value.
    retention_days_default: Mapped[int | None] = mapped_column(Integer, nullable=True)

    ai_provider_override: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ai_model_override: Mapped[str | None] = mapped_column(String(128), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    installation: Mapped["Installation"] = relationship()  # noqa: F821
    members: Mapped[list["OrganizationMember"]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )


class OrganizationMember(Base):
    """One authenticated dashboard user's role within an Organization
    (Phase 17), upserted on every dashboard login via
    `app.tenancy.membership.sync_membership`.

    Role heuristic (see that module): the installer of a personal-account
    (`account_type="User"`) Installation is `"owner"`; every other GitHub
    user reported as having installation access is inserted as `"member"`
    the first time they log in. Sync never *downgrades* an existing
    `"owner"`/`"admin"` row - promotion beyond `"member"` is a deliberate,
    dashboard-driven action (`PUT /dashboard/organizations/{id}/settings`
    equivalent membership endpoint), not something a login should silently
    undo.
    """

    __tablename__ = "organization_members"
    __table_args__ = (
        UniqueConstraint(
            "organization_id", "github_user_id", name="uq_org_members_org_user"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)

    github_user_id: Mapped[int] = mapped_column(Integer, index=True)
    login: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16), default="member")  # owner | admin | member

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    organization: Mapped["Organization"] = relationship(back_populates="members")
