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
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class ToolRun(Base):
    """One normalized deterministic-check result for a DiffSnapshot's head_sha.

    Immutable per (diff_snapshot_id, check_name), mirroring DiffSnapshot: a
    repeated pipeline run for the same head_sha reuses existing rows instead
    of recomputing them, so a result already consumed by a later decision
    can't shift under it. `conclusion` is the authoritative outcome a policy
    engine (Phase 7) must read - `passed`/`failed`/`errored`/`timed_out` are
    mutually exclusive and a `timed_out` run must never be read as `failed`
    silently passing, nor vice versa.
    """

    __tablename__ = "tool_runs"
    __table_args__ = (
        UniqueConstraint(
            "diff_snapshot_id", "check_name", name="uq_tool_runs_snapshot_check_name"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    repository_id: Mapped[int] = mapped_column(ForeignKey("repositories.id"), index=True)
    diff_snapshot_id: Mapped[int] = mapped_column(
        ForeignKey("diff_snapshots.id"), index=True
    )

    check_name: Mapped[str] = mapped_column(String(128))
    category: Mapped[str] = mapped_column(String(32))

    status: Mapped[str] = mapped_column(String(32), default="completed")
    conclusion: Mapped[str] = mapped_column(String(32))
    required: Mapped[bool] = mapped_column(Boolean, default=True)

    exit_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    summary: Mapped[str] = mapped_column(String(2000), default="")
    annotations: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)

    log_excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    log_truncated: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
