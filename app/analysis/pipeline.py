import logging
from typing import Any

from sqlalchemy.exc import IntegrityError

from app.analysis.normalize import NormalizedResult, normalize_result, normalize_skipped
from app.analysis.runner import SandboxRunner
from app.analysis.stages import build_all_stages
from app.analysis.workspace import workspace_for
from app.config import get_settings
from app.github.client import GitHubClient
from app.models import DiffSnapshot, Repository, ToolRun
from app.observability.metrics import review_stage_duration_seconds, tool_run_failures_total
from app.repo_config import RepoConfig

logger = logging.getLogger(__name__)


def _existing_tool_runs(db: Any, diff_snapshot_id: int) -> dict[str, ToolRun]:
    rows = db.query(ToolRun).filter_by(diff_snapshot_id=diff_snapshot_id).all()
    return {row.check_name: row for row in rows}


def _persist(
    db: Any, repository: Repository, diff_snapshot: DiffSnapshot, normalized: NormalizedResult
) -> ToolRun:
    row = ToolRun(
        repository_id=repository.id,
        diff_snapshot_id=diff_snapshot.id,
        check_name=normalized.check,
        category=normalized.category,
        status=normalized.status,
        conclusion=normalized.conclusion,
        required=normalized.required,
        exit_code=normalized.exit_code,
        duration_ms=normalized.duration_ms,
        summary=normalized.summary[:2000],
        annotations=normalized.annotations,
        log_excerpt=normalized.log_excerpt,
        log_truncated=normalized.log_truncated,
    )
    review_stage_duration_seconds.labels(
        stage=f"analysis.{normalized.check}", outcome=normalized.conclusion
    ).observe((normalized.duration_ms or 0) / 1000)
    if normalized.conclusion in {"errored", "failed", "timed_out"}:
        tool_run_failures_total.labels(
            check_name=normalized.check, conclusion=normalized.conclusion
        ).inc()

    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        # Another worker already persisted this (diff_snapshot, check_name) -
        # ToolRun rows are immutable per check, so defer to the existing row.
        db.rollback()
        return (
            db.query(ToolRun)
            .filter_by(diff_snapshot_id=diff_snapshot.id, check_name=normalized.check)
            .one()
        )
    return row


def run_analysis_pipeline(
    db: Any,
    client: GitHubClient,
    repository: Repository,
    diff_snapshot: DiffSnapshot,
    repo_config: RepoConfig,
    runner: SandboxRunner,
) -> list[ToolRun]:
    """Run every configured/built-in deterministic check for one immutable
    diff snapshot and persist normalized, tool-agnostic results.

    Idempotent per (diff_snapshot, check_name): a check that already has a
    stored result for this head_sha is never recomputed, so a decision made
    from an earlier run can't be invalidated by a later rerun silently
    producing a different outcome for the same commit.
    """
    settings = get_settings()
    if not settings.analysis_sandbox_enabled:
        logger.info(
            "analysis sandbox disabled, skipping deterministic checks",
            extra={"repository": repository.full_name, "head_sha": diff_snapshot.head_sha},
        )
        return []

    existing = _existing_tool_runs(db, diff_snapshot.id)

    with workspace_for(client, repository, diff_snapshot.head_sha) as workspace:
        stages = build_all_stages(repo_config, settings, workspace.host_path)
        results: list[ToolRun] = []

        for stage in stages:
            if stage.name in existing:
                results.append(existing[stage.name])
                continue

            if stage.skip_reason is not None:
                normalized = normalize_skipped(stage)
                results.append(_persist(db, repository, diff_snapshot, normalized))
                continue

            assert stage.limits is not None
            logger.info(
                "running deterministic check",
                extra={
                    "repository": repository.full_name,
                    "head_sha": diff_snapshot.head_sha,
                    "check": stage.name,
                },
            )
            raw_result = runner.run(
                image=stage.image,
                command=stage.command,
                run_subdir=workspace.run_subdir,
                limits=stage.limits,
            )
            normalized = normalize_result(stage, raw_result)
            results.append(_persist(db, repository, diff_snapshot, normalized))

            if normalized.conclusion == "errored":
                logger.error(
                    "deterministic check failed to execute",
                    extra={
                        "repository": repository.full_name,
                        "check": stage.name,
                        "summary": normalized.summary,
                    },
                )

    return results
