from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class DiffSnapshot(Base):
    """One immutable, normalized representation of the diff for a repository's
    head_sha, computed against a base_sha via the GitHub compare API.

    Immutability is enforced by the unique constraint on (repository_id, head_sha):
    a rebuild request for a head_sha that already has a snapshot must reuse the
    existing row rather than recomputing it, so a result generated for one commit
    can never be silently replaced by a result for another.

    `commits` holds bounded metadata (sha, first message line, author) for the
    commits in the compare range, capped at `_MAX_STORED_COMMITS` in the service.
    """

    __tablename__ = "diff_snapshots"
    __table_args__ = (
        UniqueConstraint("repository_id", "head_sha", name="uq_diff_snapshots_repo_head_sha"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    repository_id: Mapped[int] = mapped_column(ForeignKey("repositories.id"), index=True)
    head_sha: Mapped[str] = mapped_column(String(40))
    base_sha: Mapped[str] = mapped_column(String(40))
    merge_base_sha: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # The PullRequest this snapshot's push was synced against, stamped once at
    # creation time by `app.diffs.service.build_diff_snapshot` right after
    # `sync_pull_request_for_push` ran for the same push. Null when the push
    # had no open PR (e.g. a direct push to the target branch itself).
    #
    # This is the stable identifier later stages (checks, autofix) must use to
    # find "the PR this review belongs to" - PullRequest.head_sha is mutable
    # (overwritten by every subsequent push while this snapshot's own head_sha
    # stays fixed), so a later stage that is still slow-running when a newer
    # push lands can no longer find its PR by matching head_sha once the row
    # has moved on. Matching by this FK instead is immune to that race.
    pull_request_id: Mapped[int | None] = mapped_column(
        ForeignKey("pull_requests.id"), nullable=True
    )
    commits: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)

    # "complete" | "cancelled" (Phase 12 dashboard cancel control - a task
    # entry point checks this and no-ops rather than starting new work once
    # it's set; already-running work is not preemptively killed).
    status: Mapped[str] = mapped_column(String(32), default="complete")
    truncated: Mapped[bool] = mapped_column(Boolean, default=False)

    file_count: Mapped[int] = mapped_column(Integer, default=0)
    total_additions: Mapped[int] = mapped_column(Integer, default=0)
    total_deletions: Mapped[int] = mapped_column(Integer, default=0)
    total_changed_lines: Mapped[int] = mapped_column(Integer, default=0)
    total_patch_bytes: Mapped[int] = mapped_column(Integer, default=0)

    # Set once, at review start (Phase 8), when the in-progress Check Run is
    # created for this immutable head_sha. Null if creation failed or hasn't
    # run yet - the Phase 8 completion step creates one on the fly in that case.
    github_check_run_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    changed_files: Mapped[list["ChangedFile"]] = relationship(
        back_populates="diff_snapshot", cascade="all, delete-orphan"
    )


class ChangedFile(Base):
    """One file entry within a DiffSnapshot.

    `patch` is populated only when the file's patch text fits within the
    configured per-file size limit and the file isn't binary/a submodule;
    otherwise it stays null and `patch_truncated` records why, so oversized
    or binary content is never persisted for later prompt construction.
    When GitHub omits a patch because the file is too large, `patch` may
    instead hold the fetched full file content (`content_fetched=True`) - a
    diff-position mapping must not be run over it, since it isn't a diff.
    """

    __tablename__ = "changed_files"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    diff_snapshot_id: Mapped[int] = mapped_column(
        ForeignKey("diff_snapshots.id"), index=True
    )

    old_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    new_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    status: Mapped[str] = mapped_column(String(16))

    additions: Mapped[int] = mapped_column(Integer, default=0)
    deletions: Mapped[int] = mapped_column(Integer, default=0)
    changes: Mapped[int] = mapped_column(Integer, default=0)

    is_binary: Mapped[bool] = mapped_column(Boolean, default=False)
    is_submodule: Mapped[bool] = mapped_column(Boolean, default=False)
    is_generated: Mapped[bool] = mapped_column(Boolean, default=False)
    excluded_from_ai: Mapped[bool] = mapped_column(Boolean, default=False)

    patch: Mapped[str | None] = mapped_column(Text, nullable=True)
    patch_truncated: Mapped[bool] = mapped_column(Boolean, default=False)
    content_fetched: Mapped[bool] = mapped_column(Boolean, default=False)

    diff_snapshot: Mapped["DiffSnapshot"] = relationship(back_populates="changed_files")
