from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class AutoFixAttempt(Base):
    """One attempt to auto-generate, verify, and open a fix-PR for a single
    AIFinding. Immutable/append-only, same as every other evidence table in
    this codebase - a rerun of the pipeline for an already-attempted finding
    reuses the existing row instead of generating (and potentially pushing)
    a second fix, enforced by the unique constraint on ai_finding_id.

    `status`:
      - "pr_opened": a fix branch/commit/PR was successfully created.
      - "verification_failed": a fix was generated but a required
        deterministic check failed against it, so nothing was pushed.
      - "invalid_output": the model's response didn't pass schema validation.
      - "not_applicable": the model itself declared it couldn't produce a
        safe, self-contained fix for this finding - an expected outcome for
        findings that need a wider change than one line range.
      - "error": the model call itself failed, or a GitHub API call failed.

    No row is ever created for a finding that was simply ineligible (wrong
    category/severity, or over the per-snapshot cap) - eligibility is a pure
    filter, not an outcome worth recording per finding.
    """

    __tablename__ = "auto_fix_attempts"
    __table_args__ = (
        UniqueConstraint("ai_finding_id", name="uq_auto_fix_attempts_ai_finding_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    repository_id: Mapped[int] = mapped_column(ForeignKey("repositories.id"), index=True)
    diff_snapshot_id: Mapped[int] = mapped_column(ForeignKey("diff_snapshots.id"), index=True)
    ai_finding_id: Mapped[int] = mapped_column(ForeignKey("ai_findings.id"), index=True)

    status: Mapped[str] = mapped_column(String(32))
    branch_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    pull_request_number: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    pull_request_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
