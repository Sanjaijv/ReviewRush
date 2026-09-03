from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class TaskFailure(Base):
    """Dead-letter record for one Celery task whose retries were exhausted
    (Phase 13).

    Written once, from the shared `record_dead_letter` hook in
    `app.tasks._reliability`, at the moment a task gives up - never updated
    afterward. `resolved_at`/`resolved_by` are the only mutable fields,
    set by an operator acknowledging the failure from the dashboard; they
    exist so a known, already-handled failure can be told apart from one
    still needing attention, without ever deleting the underlying evidence.
    """

    __tablename__ = "task_failures"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    repository_id: Mapped[int | None] = mapped_column(
        ForeignKey("repositories.id"), nullable=True, index=True
    )
    diff_snapshot_id: Mapped[int | None] = mapped_column(
        ForeignKey("diff_snapshots.id"), nullable=True, index=True
    )

    task_name: Mapped[str] = mapped_column(String(128), index=True)
    task_id: Mapped[str] = mapped_column(String(64))
    task_args: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    exception_type: Mapped[str] = mapped_column(String(255))
    exception_message: Mapped[str] = mapped_column(Text)
    traceback: Mapped[str] = mapped_column(Text)

    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_by: Mapped[str | None] = mapped_column(String(255), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
