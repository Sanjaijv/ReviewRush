from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class MergeAttempt(Base):
    """Audit record of one Phase 9 auto-merge decision for a DiffSnapshot.

    Written on every invocation of the merge task, not just successful
    merges: `outcome` records why a merge was skipped (not eligible,
    already merged) just as much as why it succeeded or failed, so the
    audit trail explains every automated merge decision, not only the
    ones that actually moved code. `github_response` holds the raw merge
    API response on success, or the error body on failure - never
    re-derived from anything mutable, since the merge attempt itself is a
    one-time event.
    """

    __tablename__ = "merge_attempts"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    repository_id: Mapped[int] = mapped_column(ForeignKey("repositories.id"), index=True)
    diff_snapshot_id: Mapped[int] = mapped_column(ForeignKey("diff_snapshots.id"), index=True)
    pull_request_id: Mapped[int | None] = mapped_column(
        ForeignKey("pull_requests.id"), nullable=True
    )

    outcome: Mapped[str] = mapped_column(String(32))
    reasons: Mapped[list[str]] = mapped_column(JSONB, default=list)
    github_response: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
