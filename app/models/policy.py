from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class PolicyDecision(Base):
    """One versioned policy evaluation for a DiffSnapshot's head_sha.

    Immutable per diff_snapshot_id (enforced by the unique constraint),
    mirroring AIReview/ToolRun: a repeated evaluation request for an
    already-decided head_sha reuses the existing row instead of
    recomputing it, so an already-consumed decision can never shift under
    a later consumer (Phase 8/9). `reasons` and `evidence` make the
    decision reconstructable without re-deriving it from the underlying
    tool runs and AI review.
    """

    __tablename__ = "policy_decisions"
    __table_args__ = (
        UniqueConstraint(
            "diff_snapshot_id", name="uq_policy_decisions_diff_snapshot_id"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    repository_id: Mapped[int] = mapped_column(ForeignKey("repositories.id"), index=True)
    diff_snapshot_id: Mapped[int] = mapped_column(
        ForeignKey("diff_snapshots.id"), index=True
    )

    policy_version: Mapped[str] = mapped_column(String(32))
    decision: Mapped[str] = mapped_column(String(32))
    risk: Mapped[str] = mapped_column(String(32))
    reasons: Mapped[list[str]] = mapped_column(JSONB, default=list)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
