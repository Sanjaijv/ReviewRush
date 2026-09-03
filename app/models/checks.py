from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class ReviewComment(Base):
    """One GitHub comment (summary or inline) posted for a pull request (Phase 8).

    Scoped to `pull_request_id`, not a single DiffSnapshot: a review comment
    must be findable across reruns of the same PR at a *new* head_sha so a
    persisting finding is edited in place instead of re-posted, and a finding
    that disappears can be marked outdated. The unique constraint on
    (pull_request_id, kind, fingerprint) is what makes posting idempotent -
    a rerun that recomputes the same fingerprint reuses this row's
    `github_comment_id` rather than creating a duplicate comment.

    `kind="summary"` rows use a fixed fingerprint (one per PR); `kind="inline"`
    rows fingerprint a specific AIFinding's content (category/file/lines/title)
    so the same underlying issue survives across head_sha reruns.
    """

    __tablename__ = "review_comments"
    __table_args__ = (
        UniqueConstraint(
            "pull_request_id", "kind", "fingerprint", name="uq_review_comments_pr_kind_fingerprint"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    repository_id: Mapped[int] = mapped_column(ForeignKey("repositories.id"), index=True)
    pull_request_id: Mapped[int] = mapped_column(ForeignKey("pull_requests.id"), index=True)
    diff_snapshot_id: Mapped[int] = mapped_column(ForeignKey("diff_snapshots.id"), index=True)
    ai_finding_id: Mapped[int | None] = mapped_column(
        ForeignKey("ai_findings.id"), nullable=True
    )

    kind: Mapped[str] = mapped_column(String(16))  # "summary" | "inline"
    fingerprint: Mapped[str] = mapped_column(String(64))
    github_comment_id: Mapped[int] = mapped_column(BigInteger)
    path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    line: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="posted")  # "posted" | "outdated"
    head_sha: Mapped[str] = mapped_column(String(40))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
