from datetime import datetime
from typing import Any

from sqlalchemy import (
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
    commits: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)

    status: Mapped[str] = mapped_column(String(32), default="complete")
    truncated: Mapped[bool] = mapped_column(Boolean, default=False)

    file_count: Mapped[int] = mapped_column(Integer, default=0)
    total_additions: Mapped[int] = mapped_column(Integer, default=0)
    total_deletions: Mapped[int] = mapped_column(Integer, default=0)
    total_changed_lines: Mapped[int] = mapped_column(Integer, default=0)
    total_patch_bytes: Mapped[int] = mapped_column(Integer, default=0)

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
