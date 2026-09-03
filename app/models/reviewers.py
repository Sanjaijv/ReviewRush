from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class SpecializedReview(Base):
    """One specialized reviewer's pass (Phase 14) over an AIReview's diff.

    Purely an audit/observability record: the policy engine and GitHub
    comment renderer never read this table directly. Its findings (when
    `status == "completed"`) are merged into the parent AIReview's
    AIFinding rows by `app/reviewers/service.py`, and its verdict feeds the
    deterministic aggregation that updates the parent AIReview's
    risk/confidence/decision - this row is what lets that aggregation, and
    later evaluation work (Phase 15), be reconstructed and audited.

    Not unique per (ai_review_id, reviewer): a diff_snapshot's AIReview row
    is immutable, but idempotency for specialized reviewers is enforced by
    `app/reviewers/service.py` checking for existing rows before running,
    not by a database constraint.
    """

    __tablename__ = "specialized_reviews"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    ai_review_id: Mapped[int] = mapped_column(ForeignKey("ai_reviews.id"), index=True)
    repository_id: Mapped[int] = mapped_column(ForeignKey("repositories.id"), index=True)

    reviewer: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32))
    decision: Mapped[str | None] = mapped_column(String(32), nullable=True)
    risk: Mapped[str | None] = mapped_column(String(32), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    summary: Mapped[str] = mapped_column(Text, default="")

    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
