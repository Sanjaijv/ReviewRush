from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class AIReview(Base):
    """One AI review attempt for one immutable DiffSnapshot head_sha.

    Immutable per diff_snapshot_id (enforced by the unique constraint), same
    reasoning as DiffSnapshot/ToolRun: a rebuild request for an already-reviewed
    head_sha reuses the existing row instead of calling the model again.

    `status != "completed"` (i.e. "invalid_output" or "error") means the model
    never produced a trustworthy result for this commit - `decision`, `risk`,
    and `confidence` are null in that case, and there are no AIFinding rows.
    Any later consumer (the Phase 7 policy engine) MUST treat that as
    HUMAN_REVIEW, never as an implicit approval.

    One exception to immutability: when specialized reviewers are enabled
    (Phase 14), `app/reviewers/service.py` updates `decision`/`risk`/
    `confidence`/`summary` and adds/updates AIFinding rows exactly once,
    right after this row is first persisted with `status == "completed"` -
    guarded by its own idempotency check (the presence of any
    SpecializedReview row), never re-running on a later retry. The update
    can only move the verdict toward more caution (worse decision, higher
    risk, lower confidence), never the reverse.
    """

    __tablename__ = "ai_reviews"
    __table_args__ = (
        UniqueConstraint("diff_snapshot_id", name="uq_ai_reviews_diff_snapshot_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    repository_id: Mapped[int] = mapped_column(ForeignKey("repositories.id"), index=True)
    diff_snapshot_id: Mapped[int] = mapped_column(
        ForeignKey("diff_snapshots.id"), index=True
    )

    status: Mapped[str] = mapped_column(String(32))
    decision: Mapped[str | None] = mapped_column(String(32), nullable=True)
    risk: Mapped[str | None] = mapped_column(String(32), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    summary: Mapped[str] = mapped_column(Text, default="")

    provider: Mapped[str] = mapped_column(String(64), default="")
    model: Mapped[str] = mapped_column(String(128), default="")
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    findings: Mapped[list["AIFinding"]] = relationship(
        back_populates="ai_review", cascade="all, delete-orphan"
    )


class AIFinding(Base):
    """One issue from an AIReview's `issues[]`, matching AIReviewIssue."""

    __tablename__ = "ai_findings"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    ai_review_id: Mapped[int] = mapped_column(ForeignKey("ai_reviews.id"), index=True)
    repository_id: Mapped[int] = mapped_column(ForeignKey("repositories.id"), index=True)

    file: Mapped[str] = mapped_column(String(1024))
    start_line: Mapped[int] = mapped_column(Integer)
    end_line: Mapped[int] = mapped_column(Integer)
    severity: Mapped[str] = mapped_column(String(32))
    category: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String(200))
    evidence: Mapped[str] = mapped_column(Text)
    recommendation: Mapped[str] = mapped_column(Text, default="")
    # Ids of RepoContextSnapshot.context_items (Phase 10) the model cited as
    # supporting evidence for this finding. Empty when the finding relied
    # only on the diff itself, or when repository context was unavailable.
    context_refs: Mapped[list[str]] = mapped_column(JSONB, default=list)
    # Names of reviewers (Phase 14) that produced or agreed on this finding,
    # e.g. ["general"] or ["security", "logic_correctness"] when a
    # specialized pass collapsed into an existing finding. Always at least
    # one entry once persisted.
    contributing_reviewers: Mapped[list[str]] = mapped_column(
        JSONB, default=lambda: ["general"]
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    ai_review: Mapped["AIReview"] = relationship(back_populates="findings")
