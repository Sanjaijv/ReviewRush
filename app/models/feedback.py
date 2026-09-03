from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class FindingFeedback(Base):
    """One developer's reaction to one AIFinding (Phase 15).

    Unique on (ai_finding_id, actor_user_id): a given user's feedback on a
    given finding upserts in place rather than accumulating duplicate rows,
    mirroring how ReviewComment treats a rerun as an update, not a new
    event.

    `consent` is asserted explicitly by the submitting user at write time -
    there is no implied consent. `app.evaluation.dataset` must skip any row
    with `consent=False` when building an evaluation dataset, and
    `retention_days` records how long this row (and any dataset item derived
    from it) may be kept before a separately-run cleanup process removes it,
    the same non-self-deleting pattern `Repository.retention_days` uses.
    """

    __tablename__ = "finding_feedback"
    __table_args__ = (
        UniqueConstraint(
            "ai_finding_id", "actor_user_id", name="uq_finding_feedback_finding_actor"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    repository_id: Mapped[int] = mapped_column(ForeignKey("repositories.id"), index=True)
    ai_finding_id: Mapped[int] = mapped_column(ForeignKey("ai_findings.id"), index=True)

    # "useful" | "incorrect" | "already_known" | "not_actionable"
    reaction: Mapped[str] = mapped_column(String(32))
    # Whether the recommended change was actually implemented. Null means
    # unknown/not reported, distinct from False ("known not implemented").
    implemented: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    consent: Mapped[bool] = mapped_column(Boolean)
    # e.g. "dashboard" - where this feedback was collected, so a later
    # audit can tell provenance apart from a bulk/manual import.
    provenance: Mapped[str] = mapped_column(String(64), default="dashboard")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    retention_days: Mapped[int] = mapped_column(Integer)

    actor_user_id: Mapped[int] = mapped_column(Integer)
    actor_login: Mapped[str] = mapped_column(String(255))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class EscapedDefect(Base):
    """One defect known to have reached production despite review (Phase 15).

    Purely evidence-based bookkeeping - recorded only when a human has
    concrete proof (a revert, an incident, a follow-up bug report) that a
    reviewed change caused a problem the pipeline didn't block. `ai_finding_id`
    is set only when a specific existing finding should have caught this
    (used to compute recall against real outcomes); left null when nothing in
    the original review addressed it (a false-negative with no matching
    finding at all).
    """

    __tablename__ = "escaped_defects"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    repository_id: Mapped[int] = mapped_column(ForeignKey("repositories.id"), index=True)
    pull_request_id: Mapped[int | None] = mapped_column(
        ForeignKey("pull_requests.id"), nullable=True
    )
    diff_snapshot_id: Mapped[int | None] = mapped_column(
        ForeignKey("diff_snapshots.id"), nullable=True
    )
    ai_finding_id: Mapped[int | None] = mapped_column(
        ForeignKey("ai_findings.id"), nullable=True
    )

    description: Mapped[str] = mapped_column(Text)
    evidence_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    detected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    actor_user_id: Mapped[int] = mapped_column(Integer)
    actor_login: Mapped[str] = mapped_column(String(255))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
