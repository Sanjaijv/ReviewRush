import logging
from typing import Any

from sqlalchemy.exc import IntegrityError

from app.config import Settings, get_settings
from app.dashboard.audit import record_audit_event
from app.dashboard.config_service import get_active_config_version
from app.github.auth import get_installation_access_token
from app.github.client import GitHubClient
from app.models import AIReview, DiffSnapshot, PolicyDecision, Repository, ToolRun
from app.policy.engine import (
    AIFindingSummary,
    PolicyInput,
    PolicyResult,
    ToolCheckResult,
    evaluate_policy,
)
from app.repo_config import RepoConfig, parse_repo_config

logger = logging.getLogger(__name__)

REPO_CONFIG_PATH = ".reviewrush.yml"

_RISK_ORDER = ["low", "medium", "high", "critical"]
_RISK_RANK = {name: rank for rank, name in enumerate(_RISK_ORDER)}


def _weakest_risk(a: str, b: str) -> str:
    """The higher of two risk ceilings collapsed to the lower (stricter) one -
    repo config can only tighten the org floor, never loosen it."""
    rank_a = _RISK_RANK.get(a.lower(), _RISK_RANK["low"])
    rank_b = _RISK_RANK.get(b.lower(), _RISK_RANK["low"])
    return _RISK_ORDER[min(rank_a, rank_b)]


def _existing_policy_decision(db: Any, diff_snapshot_id: int) -> PolicyDecision | None:
    return db.query(PolicyDecision).filter_by(diff_snapshot_id=diff_snapshot_id).one_or_none()


def _build_policy_input(
    repo_config: RepoConfig,
    settings: Settings,
    diff_snapshot: DiffSnapshot,
    tool_runs: list[ToolRun],
    ai_review: AIReview | None,
) -> PolicyInput:
    configured_required_checks = [
        name for name, check in repo_config.checks.items() if check.required
    ]
    tool_results = [
        ToolCheckResult(check_name=t.check_name, required=t.required, conclusion=t.conclusion)
        for t in tool_runs
    ]

    ai_findings = (
        [AIFindingSummary(severity=f.severity, category=f.category) for f in ai_review.findings]
        if ai_review is not None
        else []
    )

    changed_paths = [
        (f.new_path or f.old_path or "") for f in diff_snapshot.changed_files
    ]

    protected_path_patterns = sorted(
        set(repo_config.protected_paths) | set(settings.policy_org_protected_paths)
    )
    min_ai_confidence = max(
        repo_config.review.minimum_ai_confidence, settings.policy_org_min_ai_confidence
    )
    max_auto_merge_risk = _weakest_risk(
        repo_config.merge.maximum_risk, settings.policy_org_max_auto_merge_risk
    )

    return PolicyInput(
        configured_required_checks=configured_required_checks,
        tool_results=tool_results,
        ai_status=ai_review.status if ai_review is not None else None,
        ai_risk=ai_review.risk if ai_review is not None else None,
        ai_confidence=ai_review.confidence if ai_review is not None else None,
        ai_findings=ai_findings,
        changed_paths=changed_paths,
        total_changed_lines=diff_snapshot.total_changed_lines,
        protected_path_patterns=protected_path_patterns,
        dependency_manifest_patterns=settings.policy_dependency_manifest_patterns,
        min_ai_confidence=min_ai_confidence,
        max_auto_merge_risk=max_auto_merge_risk,
        max_auto_mergeable_changed_lines=settings.policy_max_auto_mergeable_changed_lines,
        require_human_for_protected_paths=repo_config.merge.require_human_for_protected_paths,
    )


def _persist(
    db: Any, repository: Repository, diff_snapshot: DiffSnapshot, decision: PolicyResult
) -> PolicyDecision:
    row = PolicyDecision(
        repository_id=repository.id,
        diff_snapshot_id=diff_snapshot.id,
        policy_version=decision.policy_version,
        decision=decision.decision,
        risk=decision.risk,
        reasons=decision.reasons,
        evidence=decision.evidence,
    )
    db.add(row)
    try:
        db.flush()
        record_audit_event(
            db,
            action="policy.decided",
            target_type="policy_decision",
            target_id=str(row.id),
            repository_id=repository.id,
            metadata={
                "diff_snapshot_id": diff_snapshot.id,
                "head_sha": diff_snapshot.head_sha,
                "decision": decision.decision,
                "risk": decision.risk,
            },
        )
        db.commit()
    except IntegrityError:
        # Another worker already decided this head_sha - PolicyDecision rows
        # are immutable per diff_snapshot, so defer to the existing row.
        db.rollback()
        existing = _existing_policy_decision(db, diff_snapshot.id)
        assert existing is not None
        return existing
    return row


def run_policy_decision_for_snapshot(
    db: Any, repository: Repository, diff_snapshot: DiffSnapshot
) -> PolicyDecision:
    """Run the versioned policy engine for one immutable diff snapshot.

    Idempotent per diff_snapshot: an existing PolicyDecision row is returned
    unchanged rather than re-evaluated, so a decision already consumed by a
    later phase (checks/merge) can never shift under it. Runs regardless of
    whether the AI reviewer or deterministic pipeline produced results -
    missing results fail closed to HUMAN_REVIEW inside the engine itself,
    they never cause this function to skip and leave no decision at all.
    """
    existing = _existing_policy_decision(db, diff_snapshot.id)
    if existing is not None:
        return existing

    settings = get_settings()

    # A dashboard-authored override (Phase 12) takes precedence over the
    # committed .reviewrush.yml when one exists, so an admin can tighten
    # policy without a code change - it is still merged with the
    # organization floor below exactly like the file-based config, so it
    # can only tighten policy, never weaken it.
    active_override = get_active_config_version(db, repository.id)
    if active_override is not None:
        repo_config = RepoConfig.model_validate(active_override.config)
    else:
        installation = repository.installation
        token = get_installation_access_token(installation.github_installation_id)
        with GitHubClient(token) as client:
            config_yaml = client.get_file_contents(
                repository.owner, repository.name, REPO_CONFIG_PATH, ref=diff_snapshot.head_sha
            )
        repo_config = parse_repo_config(config_yaml)

    tool_runs = db.query(ToolRun).filter_by(diff_snapshot_id=diff_snapshot.id).all()
    ai_review = db.query(AIReview).filter_by(diff_snapshot_id=diff_snapshot.id).one_or_none()

    policy_input = _build_policy_input(repo_config, settings, diff_snapshot, tool_runs, ai_review)
    decision = evaluate_policy(policy_input)

    logger.info(
        "policy decision computed",
        extra={
            "repository": repository.full_name,
            "head_sha": diff_snapshot.head_sha,
            "decision": decision.decision,
            "risk": decision.risk,
        },
    )

    return _persist(db, repository, diff_snapshot, decision)
