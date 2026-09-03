import logging
from typing import Any

import httpx

from app.config import get_settings
from app.dashboard.audit import record_audit_event
from app.dashboard.config_service import get_active_config_version
from app.github.auth import get_installation_access_token
from app.github.client import GitHubClient
from app.merge.eligibility import (
    MergeEligibilityInput,
    RequiredCheckResult,
    evaluate_merge_eligibility,
)
from app.models import DiffSnapshot, MergeAttempt, PolicyDecision, PullRequest, Repository
from app.repo_config import RepoConfig, parse_repo_config

logger = logging.getLogger(__name__)

REPO_CONFIG_PATH = ".reviewrush.yml"


def _find_pull_request(
    db: Any, repository: Repository, diff_snapshot: DiffSnapshot
) -> PullRequest | None:
    return (
        db.query(PullRequest)
        .filter_by(repository_id=repository.id, head_sha=diff_snapshot.head_sha)
        .one_or_none()
    )


def _resolve_merge_method(repo_config_method: str, settings: Any) -> str:
    if repo_config_method in settings.merge_allowed_methods:
        return repo_config_method
    logger.warning(
        "configured merge method %r is not in the allowed list, falling back to squash",
        repo_config_method,
    )
    return "squash"


def _safe_response_json(response: httpx.Response) -> dict[str, Any]:
    try:
        body = response.json()
    except ValueError:
        return {"status_code": response.status_code, "text": response.text[:2000]}
    return body if isinstance(body, dict) else {"status_code": response.status_code, "body": body}


def _record_attempt(
    db: Any,
    repository: Repository,
    diff_snapshot: DiffSnapshot,
    pull_request: PullRequest | None,
    outcome: str,
    reasons: list[str],
    github_response: dict[str, Any] | None = None,
) -> MergeAttempt:
    row = MergeAttempt(
        repository_id=repository.id,
        diff_snapshot_id=diff_snapshot.id,
        pull_request_id=pull_request.id if pull_request is not None else None,
        outcome=outcome,
        reasons=reasons,
        github_response=github_response,
    )
    db.add(row)
    db.flush()
    record_audit_event(
        db,
        action="merge.attempted",
        target_type="merge_attempt",
        target_id=str(row.id),
        repository_id=repository.id,
        metadata={
            "diff_snapshot_id": diff_snapshot.id,
            "head_sha": diff_snapshot.head_sha,
            "outcome": outcome,
            "reasons": reasons,
        },
    )
    db.commit()
    logger.info(
        "auto-merge attempt recorded",
        extra={
            "repository": repository.full_name,
            "head_sha": diff_snapshot.head_sha,
            "outcome": outcome,
        },
    )
    return row


def attempt_auto_merge_for_snapshot(
    db: Any, repository: Repository, diff_snapshot: DiffSnapshot
) -> MergeAttempt:
    """Phase 9: decide and, if eligible, execute an auto-merge for one
    reviewed DiffSnapshot. Always writes a MergeAttempt audit row, whether
    or not a merge was actually attempted.

    Every fact that matters is re-fetched live from GitHub immediately
    before deciding - the PR row, its check runs, and its reviews - so a
    push that landed after the PolicyDecision was computed can never be
    merged on the strength of a now-stale review.
    """
    decision = db.query(PolicyDecision).filter_by(diff_snapshot_id=diff_snapshot.id).one_or_none()
    if decision is None:
        logger.info(
            "no policy decision found, skipping auto-merge",
            extra={"repository": repository.full_name, "head_sha": diff_snapshot.head_sha},
        )
        return _record_attempt(
            db, repository, diff_snapshot, None, "skipped", ["no policy decision found"]
        )

    pull_request = _find_pull_request(db, repository, diff_snapshot)
    if pull_request is None:
        logger.info(
            "no pull request found for this head_sha, skipping auto-merge",
            extra={"repository": repository.full_name, "head_sha": diff_snapshot.head_sha},
        )
        return _record_attempt(
            db,
            repository,
            diff_snapshot,
            None,
            "skipped",
            ["no open pull request for this head_sha"],
        )

    settings = get_settings()
    installation = repository.installation
    token = get_installation_access_token(installation.github_installation_id)

    active_override = get_active_config_version(db, repository.id)

    with GitHubClient(token) as client:
        if active_override is not None:
            repo_config = RepoConfig.model_validate(active_override.config)
        else:
            config_yaml = client.get_file_contents(
                repository.owner, repository.name, REPO_CONFIG_PATH, ref=diff_snapshot.head_sha
            )
            repo_config = parse_repo_config(config_yaml)

        live_pr = client.get_pull_request(
            repository.owner, repository.name, pull_request.github_pr_number
        )
        check_runs_payload = client.list_check_runs_for_ref(
            repository.owner, repository.name, diff_snapshot.head_sha
        )
        reviews = client.list_reviews(
            repository.owner, repository.name, pull_request.github_pr_number
        )

        check_runs = [
            RequiredCheckResult(
                name=run.get("name", ""),
                status=run.get("status", ""),
                conclusion=run.get("conclusion"),
            )
            for run in check_runs_payload.get("check_runs", [])
        ]
        changes_requested = sum(1 for r in reviews if r.get("state") == "CHANGES_REQUESTED")
        protected_matched = bool(decision.evidence.get("protected_paths_matched"))

        eligibility_input = MergeEligibilityInput(
            auto_merge_enabled=settings.merge_auto_merge_enabled and repo_config.merge.enabled,
            policy_decision=decision.decision,
            policy_risk=decision.risk,
            protected_paths_matched=protected_matched,
            reviewed_head_sha=diff_snapshot.head_sha,
            pr_head_sha=(live_pr.get("head") or {}).get("sha", ""),
            pr_base_branch=(live_pr.get("base") or {}).get("ref", ""),
            expected_base_branch=pull_request.base_branch,
            pr_state=live_pr.get("state", "unknown"),
            pr_merged=bool(live_pr.get("merged")),
            pr_draft=bool(live_pr.get("draft")),
            mergeable=live_pr.get("mergeable"),
            mergeable_state=live_pr.get("mergeable_state"),
            check_runs=check_runs,
            changes_requested_reviews=changes_requested,
        )
        result = evaluate_merge_eligibility(eligibility_input)

        if not result.eligible:
            outcome = "already_merged" if eligibility_input.pr_merged else "not_eligible"
            logger.info(
                "pull request not eligible for auto-merge",
                extra={
                    "repository": repository.full_name,
                    "head_sha": diff_snapshot.head_sha,
                    "reasons": result.reasons,
                },
            )
            return _record_attempt(
                db, repository, diff_snapshot, pull_request, outcome, result.reasons
            )

        merge_method = _resolve_merge_method(repo_config.merge.method, settings)
        try:
            merge_response = client.merge_pull_request(
                repository.owner,
                repository.name,
                pull_request.github_pr_number,
                sha=diff_snapshot.head_sha,
                merge_method=merge_method,
            )
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "auto-merge request rejected by github",
                extra={
                    "repository": repository.full_name,
                    "head_sha": diff_snapshot.head_sha,
                    "status_code": exc.response.status_code,
                },
            )
            return _record_attempt(
                db,
                repository,
                diff_snapshot,
                pull_request,
                "failed",
                [f"github merge request failed with status {exc.response.status_code}"],
                github_response=_safe_response_json(exc.response),
            )

        pull_request.state = "merged"
        db.commit()
        logger.info(
            "auto-merged pull request",
            extra={
                "repository": repository.full_name,
                "head_sha": diff_snapshot.head_sha,
                "pr_number": pull_request.github_pr_number,
            },
        )
        return _record_attempt(
            db,
            repository,
            diff_snapshot,
            pull_request,
            "merged",
            result.reasons,
            github_response=merge_response,
        )
