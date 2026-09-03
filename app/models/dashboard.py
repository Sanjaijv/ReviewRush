from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class AuditEvent(Base):
    """Immutable, append-only record of one config, review, approval, merge,
    or dashboard-control event (Phase 12).

    Never updated or deleted by application code - it is the reconstruction
    trail the Phase 12 acceptance criteria require ("every merge decision
    can be reconstructed from stored evidence", "settings changes are
    versioned and identify the actor"). `actor_type="system"` rows are
    written by automated pipeline stages (policy decisions, merge attempts);
    `actor_type="user"` rows are written by an authenticated dashboard
    action and always carry `actor_user_id`/`actor_login`. `metadata` must
    never hold raw secrets, tokens, or full repository content - callers are
    responsible for passing only already-redacted summaries, the same rule
    Section 7 applies to logs and prompts.
    """

    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    repository_id: Mapped[int | None] = mapped_column(
        ForeignKey("repositories.id"), nullable=True, index=True
    )

    actor_type: Mapped[str] = mapped_column(String(16))  # "user" | "system"
    actor_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    actor_login: Mapped[str | None] = mapped_column(String(255), nullable=True)

    action: Mapped[str] = mapped_column(String(64), index=True)
    target_type: Mapped[str] = mapped_column(String(64))
    target_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    event_metadata: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RepositoryConfigVersion(Base):
    """One versioned, dashboard-authored override of a repository's effective
    `.reviewrush.yml` (Phase 12 "configuration editor").

    Rows are immutable and additive, mirroring DiffSnapshot/PolicyDecision:
    saving a change inserts a new row with `version = previous + 1` rather
    than mutating the previous one, so history and the responsible actor are
    always reconstructable. The highest `version` for a repository is the
    active override. `config` is a `RepoConfig`-shaped document that has
    already passed schema validation *before* being written - callers must
    never persist an unvalidated document. This override changes only what
    `app.repo_config` would otherwise read from the committed
    `.reviewrush.yml`; it is still merged with the organization policy floor
    in `app.policy.service` exactly like the file-based config is, so a
    dashboard edit can tighten policy but never weaken it below the floor.
    """

    __tablename__ = "repository_config_versions"
    __table_args__ = (
        UniqueConstraint(
            "repository_id", "version", name="uq_repository_config_versions_repo_version"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    repository_id: Mapped[int] = mapped_column(ForeignKey("repositories.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)

    config: Mapped[dict[str, Any]] = mapped_column(JSONB)

    actor_user_id: Mapped[int] = mapped_column(Integer)
    actor_login: Mapped[str] = mapped_column(String(255))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
