"""Feedback collection and model evaluation: finding_feedback, escaped_defects,
benchmark_cases, eval_dataset_versions, eval_dataset_items, eval_runs,
model_promotions.

Revision ID: 0015
Revises: 0014
Create Date: 2026-09-03

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "finding_feedback",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("repository_id", sa.Integer(), sa.ForeignKey("repositories.id"), nullable=False),
        sa.Column("ai_finding_id", sa.Integer(), sa.ForeignKey("ai_findings.id"), nullable=False),
        sa.Column("reaction", sa.String(length=32), nullable=False),
        sa.Column("implemented", sa.Boolean(), nullable=True),
        sa.Column("consent", sa.Boolean(), nullable=False),
        sa.Column("provenance", sa.String(length=64), nullable=False, server_default="dashboard"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("retention_days", sa.Integer(), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), nullable=False),
        sa.Column("actor_login", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint(
            "ai_finding_id", "actor_user_id", name="uq_finding_feedback_finding_actor"
        ),
    )
    op.create_index("ix_finding_feedback_repository_id", "finding_feedback", ["repository_id"])
    op.create_index("ix_finding_feedback_ai_finding_id", "finding_feedback", ["ai_finding_id"])

    op.create_table(
        "escaped_defects",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("repository_id", sa.Integer(), sa.ForeignKey("repositories.id"), nullable=False),
        sa.Column(
            "pull_request_id", sa.Integer(), sa.ForeignKey("pull_requests.id"), nullable=True
        ),
        sa.Column(
            "diff_snapshot_id", sa.Integer(), sa.ForeignKey("diff_snapshots.id"), nullable=True
        ),
        sa.Column("ai_finding_id", sa.Integer(), sa.ForeignKey("ai_findings.id"), nullable=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("evidence_url", sa.String(length=2048), nullable=True),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("actor_user_id", sa.Integer(), nullable=False),
        sa.Column("actor_login", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_escaped_defects_repository_id", "escaped_defects", ["repository_id"])

    op.create_table(
        "benchmark_cases",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("slug", sa.String(length=128), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("file_path", sa.String(length=1024), nullable=False),
        sa.Column("diff_text", sa.Text(), nullable=False),
        sa.Column(
            "expected_findings",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("slug", name="uq_benchmark_cases_slug"),
    )

    op.create_table(
        "eval_dataset_versions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("item_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("actor_user_id", sa.Integer(), nullable=False),
        sa.Column("actor_login", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("version", name="uq_eval_dataset_versions_version"),
    )

    op.create_table(
        "eval_dataset_items",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "dataset_version_id",
            sa.Integer(),
            sa.ForeignKey("eval_dataset_versions.id"),
            nullable=False,
        ),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("repository_ref", sa.String(length=64), nullable=False),
        sa.Column("diff_text", sa.Text(), nullable=False),
        sa.Column(
            "expected_findings",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
        sa.Column(
            "source_ai_finding_id", sa.Integer(), sa.ForeignKey("ai_findings.id"), nullable=True
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index(
        "ix_eval_dataset_items_dataset_version_id", "eval_dataset_items", ["dataset_version_id"]
    )

    op.create_table(
        "eval_runs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("run_type", sa.String(length=16), nullable=False),
        sa.Column(
            "dataset_version_id",
            sa.Integer(),
            sa.ForeignKey("eval_dataset_versions.id"),
            nullable=True,
        ),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("prompt_version", sa.String(length=32), nullable=False),
        sa.Column("policy_version", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("case_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "metrics", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("actor_user_id", sa.Integer(), nullable=True),
        sa.Column("actor_login", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )

    op.create_table(
        "model_promotions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("eval_run_id", sa.Integer(), sa.ForeignKey("eval_runs.id"), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("prompt_version", sa.String(length=32), nullable=False),
        sa.Column("policy_version", sa.String(length=32), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("actor_user_id", sa.Integer(), nullable=False),
        sa.Column("actor_login", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )


def downgrade() -> None:
    op.drop_table("model_promotions")
    op.drop_table("eval_runs")
    op.drop_index("ix_eval_dataset_items_dataset_version_id", table_name="eval_dataset_items")
    op.drop_table("eval_dataset_items")
    op.drop_table("eval_dataset_versions")
    op.drop_table("benchmark_cases")
    op.drop_index("ix_escaped_defects_repository_id", table_name="escaped_defects")
    op.drop_table("escaped_defects")
    op.drop_index("ix_finding_feedback_ai_finding_id", table_name="finding_feedback")
    op.drop_index("ix_finding_feedback_repository_id", table_name="finding_feedback")
    op.drop_table("finding_feedback")
