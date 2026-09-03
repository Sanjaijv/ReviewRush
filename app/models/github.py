from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class Installation(Base):
    """A GitHub App installation on an account (org or user)."""

    __tablename__ = "installations"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    github_installation_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    account_login: Mapped[str] = mapped_column(String(255))
    account_type: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    repositories: Mapped[list["Repository"]] = relationship(back_populates="installation")


class Repository(Base):
    """A repository accessible to an installation."""

    __tablename__ = "repositories"
    __table_args__ = (UniqueConstraint("github_repo_id", name="uq_repositories_github_repo_id"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    installation_id: Mapped[int] = mapped_column(ForeignKey("installations.id"), index=True)
    github_repo_id: Mapped[int] = mapped_column(BigInteger)
    owner: Mapped[str] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(511))
    default_branch: Mapped[str] = mapped_column(String(255), default="main")
    source_branch: Mapped[str | None] = mapped_column(String(255), nullable=True)
    target_branch: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(default=True)
    # Dashboard "repository-disconnect" control (Phase 12). A disconnected
    # repository is treated as inactive (is_active is cleared alongside
    # these) - new webhook activity for it is ignored. retention_days
    # records how long stored review evidence should be kept before a
    # (separately scheduled) cleanup process removes it; it does not itself
    # delete anything.
    disconnected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    disconnected_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    retention_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    installation: Mapped["Installation"] = relationship(back_populates="repositories")
    pull_requests: Mapped[list["PullRequest"]] = relationship(back_populates="repository")


class PullRequest(Base):
    """One GitHub pull request automatically maintained between a source and
    target branch. head_sha/base_sha reflect the last push this record was
    synchronized against — later phases must never treat a decision made for
    an older head_sha as valid for a newer one.
    """

    __tablename__ = "pull_requests"
    __table_args__ = (
        UniqueConstraint(
            "repository_id", "github_pr_number", name="uq_pull_requests_repo_pr_number"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    repository_id: Mapped[int] = mapped_column(ForeignKey("repositories.id"), index=True)
    github_pr_number: Mapped[int] = mapped_column()
    head_branch: Mapped[str] = mapped_column(String(255))
    base_branch: Mapped[str] = mapped_column(String(255))
    head_sha: Mapped[str] = mapped_column(String(40))
    base_sha: Mapped[str | None] = mapped_column(String(40), nullable=True)
    state: Mapped[str] = mapped_column(String(32), default="open")
    last_synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    repository: Mapped["Repository"] = relationship(back_populates="pull_requests")


class WebhookDelivery(Base):
    """Idempotency record for one GitHub webhook delivery.

    The unique constraint on delivery_id is what makes replay detection safe under
    concurrent duplicate deliveries, not just an application-level lookup.
    """

    __tablename__ = "webhook_deliveries"
    __table_args__ = (UniqueConstraint("delivery_id", name="uq_webhook_deliveries_delivery_id"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    delivery_id: Mapped[str] = mapped_column(String(255), index=True)
    event_type: Mapped[str] = mapped_column(String(64))
    action: Mapped[str | None] = mapped_column(String(64), nullable=True)
    github_installation_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="received")
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
