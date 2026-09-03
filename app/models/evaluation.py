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


class BenchmarkCase(Base):
    """One fixed, code-defined benchmark item (Phase 15).

    Rows are seeded and kept in sync from `app/evaluation/benchmark.py`'s
    fixture list via `load_fixed_benchmark_cases()` (idempotent upsert by
    `slug`) - never authored through the API, unlike EvalDatasetItem. This
    is the frozen ground-truth set the roadmap requires ("clean diffs, known
    bugs, security issues, and adversarial prompt-injection cases"), so a
    model/prompt/policy change can be measured against a fixed target
    instead of a moving one.
    """

    __tablename__ = "benchmark_cases"
    __table_args__ = (UniqueConstraint("slug", name="uq_benchmark_cases_slug"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    slug: Mapped[str] = mapped_column(String(128))
    # "clean" | "known_bug" | "security" | "prompt_injection"
    category: Mapped[str] = mapped_column(String(32))
    description: Mapped[str] = mapped_column(Text)
    file_path: Mapped[str] = mapped_column(String(1024))
    diff_text: Mapped[str] = mapped_column(Text)
    # Expected AIReviewIssue-shaped hints used for matching, e.g.
    # [{"category": "security", "min_severity": "high", "line_hint": 12}].
    # Empty for "clean" cases, where the model is expected to report nothing
    # at or above checks_min_inline_severity.
    expected_findings: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class EvalDatasetVersion(Base):
    """One immutable, versioned snapshot of the de-identified evaluation
    dataset (Phase 15), built from consented production feedback.

    Rows are additive, mirroring RepositoryConfigVersion: building a new
    dataset inserts `version = previous + 1` plus its EvalDatasetItem rows,
    it never mutates a prior version, so a past evaluation stays
    reproducible against the exact dataset it was run on.
    """

    __tablename__ = "eval_dataset_versions"
    __table_args__ = (UniqueConstraint("version", name="uq_eval_dataset_versions_version"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    version: Mapped[int] = mapped_column(Integer)
    item_count: Mapped[int] = mapped_column(Integer, default=0)
    notes: Mapped[str] = mapped_column(Text, default="")

    actor_user_id: Mapped[int] = mapped_column(Integer)
    actor_login: Mapped[str] = mapped_column(String(255))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EvalDatasetItem(Base):
    """One de-identified example within an EvalDatasetVersion (Phase 15).

    `diff_text` and `repository_ref` have already passed through
    `app.evaluation.redaction` before being written here - this table must
    never hold a real repository name, secret-shaped token, or commit
    author/email. `source_ai_finding_id`/`source_feedback_id` are kept only
    for internal reproducibility of the export, not exposed outside the
    evaluation admin surface.
    """

    __tablename__ = "eval_dataset_items"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    dataset_version_id: Mapped[int] = mapped_column(
        ForeignKey("eval_dataset_versions.id"), index=True
    )

    category: Mapped[str] = mapped_column(String(32))
    repository_ref: Mapped[str] = mapped_column(String(64))
    diff_text: Mapped[str] = mapped_column(Text)
    expected_findings: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)

    source_ai_finding_id: Mapped[int | None] = mapped_column(
        ForeignKey("ai_findings.id"), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EvalRun(Base):
    """One offline evaluation of a provider/model/prompt/policy combination
    against either the fixed benchmark or an EvalDatasetVersion (Phase 15).

    Immutable once `status == "completed"` - `app.evaluation.promotion`
    reads `metrics` off this row and never recomputes it, so a promotion
    decision always traces back to one frozen, reproducible run.
    """

    __tablename__ = "eval_runs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # "benchmark" | "dataset"
    run_type: Mapped[str] = mapped_column(String(16))
    dataset_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("eval_dataset_versions.id"), nullable=True
    )

    provider: Mapped[str] = mapped_column(String(64))
    model: Mapped[str] = mapped_column(String(128))
    prompt_version: Mapped[str] = mapped_column(String(32))
    policy_version: Mapped[str] = mapped_column(String(32))

    status: Mapped[str] = mapped_column(String(32))  # "completed" | "error"
    case_count: Mapped[int] = mapped_column(Integer, default=0)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    actor_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    actor_login: Mapped[str | None] = mapped_column(String(255), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ModelPromotion(Base):
    """Record that a provider/model/prompt/policy combination was approved
    for production use (Phase 15).

    `eval_run_id` is NOT NULL and has no default - this is the entire
    enforcement mechanism for the Phase 15 acceptance criterion "model or
    prompt changes cannot be promoted without benchmark results". There is
    no code path in `app.evaluation.promotion.promote_configuration` that
    creates a row here without first validating a completed EvalRun whose
    metrics meet the configured minimum thresholds - never bypass that
    function to insert a row directly.
    """

    __tablename__ = "model_promotions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    eval_run_id: Mapped[int] = mapped_column(ForeignKey("eval_runs.id"))

    provider: Mapped[str] = mapped_column(String(64))
    model: Mapped[str] = mapped_column(String(128))
    prompt_version: Mapped[str] = mapped_column(String(32))
    policy_version: Mapped[str] = mapped_column(String(32))
    notes: Mapped[str] = mapped_column(Text, default="")

    actor_user_id: Mapped[int] = mapped_column(Integer)
    actor_login: Mapped[str] = mapped_column(String(255))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
