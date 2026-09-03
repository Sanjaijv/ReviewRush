"""Fine-tuning and shadow evaluation (Phase 16): finetune_jobs, shadow_eval_results.

Revision ID: 0016
Revises: 0015
Create Date: 2026-09-03

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "finetune_jobs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "dataset_version_id",
            sa.Integer(),
            sa.ForeignKey("eval_dataset_versions.id"),
            nullable=False,
        ),
        sa.Column("base_model", sa.String(length=128), nullable=False),
        sa.Column("method", sa.String(length=16), nullable=False),
        sa.Column(
            "hyperparams", postgresql.JSONB(astext_type=sa.Text()), nullable=False,
            server_default="{}",
        ),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("training_example_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("adapter_path", sa.String(length=1024), nullable=True),
        sa.Column("output_model", sa.String(length=128), nullable=True),
        sa.Column("log_excerpt", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("actor_user_id", sa.Integer(), nullable=False),
        sa.Column("actor_login", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_finetune_jobs_dataset_version_id", "finetune_jobs", ["dataset_version_id"]
    )

    op.create_table(
        "shadow_eval_results",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("ai_review_id", sa.Integer(), sa.ForeignKey("ai_reviews.id"), nullable=False),
        sa.Column(
            "finetune_job_id", sa.Integer(), sa.ForeignKey("finetune_jobs.id"), nullable=True
        ),
        sa.Column("candidate_provider", sa.String(length=64), nullable=False),
        sa.Column("candidate_model", sa.String(length=128), nullable=False),
        sa.Column("live_issue_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("candidate_issue_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "comparison", postgresql.JSONB(astext_type=sa.Text()), nullable=False,
            server_default="{}",
        ),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="completed"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_shadow_eval_results_ai_review_id", "shadow_eval_results", ["ai_review_id"])


def downgrade() -> None:
    op.drop_index("ix_shadow_eval_results_ai_review_id", table_name="shadow_eval_results")
    op.drop_table("shadow_eval_results")
    op.drop_index("ix_finetune_jobs_dataset_version_id", table_name="finetune_jobs")
    op.drop_table("finetune_jobs")
