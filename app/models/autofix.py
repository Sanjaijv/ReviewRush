from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class AutoFixAttempt(Base):
    """One attempt to auto-generate and verify a fix for a single AIFinding,
    then either open a fix-PR (automatic trigger) or commit it directly to
    the reviewed branch (manual trigger). Immutable/append-only, same as
    every other evidence table in this codebase - a rerun of the pipeline
    for an already-attempted finding reuses the existing row instead of
    generating (and potentially pushing) a second fix, enforced by the
    unique constraint on ai_finding_id. A failed manual attempt is not
    retried through this same mechanism - see `app.autofix.service.
    apply_manual_fix`.

    `trigger`:
      - "automatic": queued for every eligible finding on a completed
        review, no human action involved (the original Phase behavior).
      - "manual": a human checked the "Apply this fix" checkbox rendered on
        a finding's comment. Only offered for findings automatic auto-fix
        would never attempt on its own (`category="security"`, or above the
        repo's configured severity ceiling) - see `manual_fix_eligible`.

    `status`:
      - "pr_opened": a fix branch/commit/PR was successfully created
        (`trigger="automatic"` only).
      - "committed": the fix was committed directly to the reviewed branch
        (`trigger="manual"` only) - see `commit_sha`.
      - "verification_failed": a fix was generated but a required
        deterministic check failed against it, so nothing was pushed.
      - "invalid_output": the model's response didn't pass schema validation.
      - "not_applicable": the model itself declared it couldn't produce a
        safe, self-contained fix for this finding - an expected outcome for
        findings that need a wider change than one line range.
      - "stale_target": (manual only) the target file changed on the branch
        after this finding was reported and before the fix could be
        committed - refusing to blindly overwrite whatever changed it.
      - "error": the model call itself failed, or a GitHub API call failed.

    No row is ever created for a finding that was simply ineligible for its
    trigger (wrong category/severity for automatic, or over the
    per-snapshot cap) - eligibility is a pure filter, not an outcome worth
    recording per finding.
    """

    __tablename__ = "auto_fix_attempts"
    __table_args__ = (
        UniqueConstraint("ai_finding_id", name="uq_auto_fix_attempts_ai_finding_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    repository_id: Mapped[int] = mapped_column(ForeignKey("repositories.id"), index=True)
    diff_snapshot_id: Mapped[int] = mapped_column(ForeignKey("diff_snapshots.id"), index=True)
    ai_finding_id: Mapped[int] = mapped_column(ForeignKey("ai_findings.id"), index=True)

    # "automatic" | "manual"
    trigger: Mapped[str] = mapped_column(String(16), default="automatic")
    status: Mapped[str] = mapped_column(String(32))
    branch_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    pull_request_number: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    pull_request_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    # Set only for trigger="manual", status="committed" - the commit pushed
    # directly to the reviewed branch.
    commit_sha: Mapped[str | None] = mapped_column(String(40), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    # GitHub login of the human who checked the "Apply this fix" checkbox.
    # Null for trigger="automatic".
    actor_login: Mapped[str | None] = mapped_column(String(255), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
