from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class FineTuneJob(Base):
    """One custom-model fine-tuning attempt (Phase 16).

    Deliberately narrow: this row tracks a *training attempt* against a
    frozen `EvalDatasetVersion` (Phase 15's already redacted/pseudonymized/
    consent-filtered export), not a live model. A job only becomes eligible
    for production traffic by going through the normal Phase 15
    `app.evaluation.promotion.promote_configuration` gate against its own
    `output_model` - there is no shortcut here that lets a completed
    FineTuneJob influence the live reviewer on its own. `adapter_path` and
    `output_model` are filled in by `app.finetune.training` only after the
    external trainer process (or, if `finetune_ollama_create_enabled`, the
    `ollama create` registration step) actually succeeds - a "completed"
    status always has both set.
    """

    __tablename__ = "finetune_jobs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    dataset_version_id: Mapped[int] = mapped_column(ForeignKey("eval_dataset_versions.id"))

    base_model: Mapped[str] = mapped_column(String(128))
    # "lora" | "qlora"
    method: Mapped[str] = mapped_column(String(16))
    hyperparams: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

    # "pending" | "running" | "completed" | "failed"
    status: Mapped[str] = mapped_column(String(32), default="pending")
    training_example_count: Mapped[int] = mapped_column(Integer, default=0)

    # Filesystem path to the trained LoRA/QLoRA adapter, produced by the
    # external trainer command configured via `finetune_trainer_command`.
    adapter_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    # The model tag the fine-tuned model is reachable under through the
    # existing provider-neutral `ReviewModel` interface (e.g. an Ollama tag
    # created with `ollama create <output_model> -f Modelfile`).
    output_model: Mapped[str | None] = mapped_column(String(128), nullable=True)

    log_excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")

    actor_user_id: Mapped[int] = mapped_column(Integer)
    actor_login: Mapped[str] = mapped_column(String(255))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ShadowEvalResult(Base):
    """One canary/shadow comparison of a candidate fine-tuned model against
    the live reviewer's output on an already-completed review (Phase 16).

    Purely observational: this table is written *after* the live AIReview,
    ReviewComments, PolicyDecision, and any merge attempt already exist and
    were decided from the live model alone. Nothing reads this table on the
    merge-decision path - it exists only so a candidate model's real-world
    behavior can be compared before it is ever promoted, per the roadmap's
    "use canary/shadow traffic before allowing the model to influence merge
    decisions."
    """

    __tablename__ = "shadow_eval_results"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    ai_review_id: Mapped[int] = mapped_column(ForeignKey("ai_reviews.id"), index=True)
    finetune_job_id: Mapped[int | None] = mapped_column(
        ForeignKey("finetune_jobs.id"), nullable=True
    )

    candidate_provider: Mapped[str] = mapped_column(String(64))
    candidate_model: Mapped[str] = mapped_column(String(128))

    live_issue_count: Mapped[int] = mapped_column(Integer, default=0)
    candidate_issue_count: Mapped[int] = mapped_column(Integer, default=0)
    # Categories/decision the candidate disagreed with the live model on -
    # informational only, e.g. {"decision_diff": true, "category_overlap": 0.5}.
    comparison: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

    status: Mapped[str] = mapped_column(String(32), default="completed")  # "completed" | "error"
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
