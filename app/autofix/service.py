import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy.exc import IntegrityError

from app.ai.model import ReviewModel, build_review_model
from app.analysis.normalize import normalize_result
from app.analysis.runner import DockerCliSandboxRunner
from app.analysis.stages import build_all_stages
from app.analysis.workspace import workspace_for
from app.autofix.prompt import build_fix_prompt
from app.autofix.schema import FixSuggestion
from app.autofix.validation import validate_fix_suggestion
from app.checks.rendering import mark_manual_fix_applied, mark_manual_fix_failed
from app.config import Settings, get_settings
from app.dashboard.audit import record_audit_event
from app.github.client import GitHubClient
from app.models import (
    AIFinding,
    AIReview,
    AutoFixAttempt,
    DiffSnapshot,
    PullRequest,
    Repository,
    ReviewComment,
)
from app.repo_config import RepoConfig, parse_repo_config

logger = logging.getLogger(__name__)

REPO_CONFIG_PATH = ".reviewrush.yml"

# category="security" is never eligible regardless of repo config - see
# AutoFixConfig's docstring. category="missing_tests" doesn't fit the
# line-range-replacement model (it needs a new file, not an edit to an
# existing range), so it's excluded on structural grounds, not a safety one.
_INELIGIBLE_CATEGORIES = {"security", "missing_tests"}
_SEVERITY_ORDER = ["low", "medium", "high", "critical"]


def _allowed_severities(maximum_severity: str) -> set[str]:
    try:
        ceiling = _SEVERITY_ORDER.index(maximum_severity)
    except ValueError:
        ceiling = 0
    # Hard cap at "medium" (index 1) no matter what a repo config claims -
    # AutoFixConfig.maximum_severity is typed to reject "high"/"critical"
    # already, but this is the enforcement point, not just the schema.
    ceiling = min(ceiling, 1)
    return set(_SEVERITY_ORDER[: ceiling + 1])


def eligible_findings(
    db: Any, ai_review: AIReview, repo_config: RepoConfig, settings: Settings
) -> list[AIFinding]:
    """Findings eligible for an auto-fix attempt: not security/missing_tests,
    within the repo's configured severity ceiling, and not already attempted
    (idempotent across reruns). Capped at `autofix_max_fixes_per_snapshot` so
    one review can never fan out into an unbounded number of fix-PRs.
    """
    if not repo_config.auto_fix.enabled:
        return []

    allowed_severities = _allowed_severities(repo_config.auto_fix.maximum_severity)
    already_attempted = {
        row.ai_finding_id
        for row in db.query(AutoFixAttempt.ai_finding_id)
        .filter(AutoFixAttempt.ai_finding_id.in_([f.id for f in ai_review.findings]))
        .all()
    }

    eligible = [
        finding
        for finding in ai_review.findings
        if finding.category not in _INELIGIBLE_CATEGORIES
        and finding.severity in allowed_severities
        and finding.id not in already_attempted
    ]
    return eligible[: settings.autofix_max_fixes_per_snapshot]


def manual_fix_eligible(finding: AIFinding, repo_config: RepoConfig, settings: Settings) -> bool:
    """Whether `finding` should be offered the "Apply this fix" checkbox
    (`app.checks.rendering.render_inline_comment_body`).

    Deliberately the complement of `eligible_findings`'s automatic filter,
    minus the structural `missing_tests` exclusion (which applies either
    way - it needs a new file, not a line-range edit): a human can ask for
    a fix attempt on exactly the findings automatic auto-fix would never
    attempt on its own (`category="security"`, or above the repo's
    configured severity ceiling). A finding automatic auto-fix would
    already attempt gets no checkbox - it's either already been attempted,
    or is about to be, without anyone needing to click anything.
    """
    if not settings.autofix_enabled or not repo_config.auto_fix.enabled:
        return False
    if finding.category == "missing_tests":
        return False
    allowed_severities = _allowed_severities(repo_config.auto_fix.maximum_severity)
    auto_eligible = (
        finding.category not in _INELIGIBLE_CATEGORIES and finding.severity in allowed_severities
    )
    return not auto_eligible


@dataclass(frozen=True)
class _GeneratedFix:
    new_content: str
    suggestion: FixSuggestion


def _generate_and_verify_fix(
    repository: Repository,
    finding: AIFinding,
    repo_config: RepoConfig,
    settings: Settings,
    workspace: Any,
) -> tuple[_GeneratedFix | None, str | None, str | None]:
    """Shared by `attempt_fix` and `apply_manual_fix`: read the finding's
    file from `workspace`, generate a candidate fix, apply it in place
    within the workspace, and verify it against this repo's required
    deterministic checks. Returns `(result, None, None)` on success, or
    `(None, failure_status, failure_message)` - exactly one of the two
    tuple shapes, never a mix.

    Deliberately stops at "verified in the workspace" - pushing the result
    (opening a fix-PR vs. committing directly to a branch) is the one thing
    that differs between the two callers, and lives in each of them.
    """
    target_path = (workspace.host_path / finding.file).resolve()
    if not str(target_path).startswith(str(workspace.host_path.resolve()) + "/"):
        return None, "error", f"finding file path escapes workspace: {finding.file}"
    if not target_path.is_file():
        return None, "error", f"finding file not found in workspace: {finding.file}"

    file_content = target_path.read_text(encoding="utf-8", errors="replace")
    system, user = build_fix_prompt(finding, file_content, repository)

    model = build_review_model(settings)
    if model is None:
        return None, "error", f"unknown AI provider: {settings.ai_provider}"

    suggestion, error = _generate_suggestion(model, system, user)
    if suggestion is None:
        return None, "invalid_output", error
    if not suggestion.applicable:
        return None, "not_applicable", suggestion.explanation or None

    original_lines = file_content.splitlines()
    new_lines = (
        original_lines[: finding.start_line - 1]
        + suggestion.replacement_lines
        + original_lines[finding.end_line :]
    )
    new_content = "\n".join(new_lines) + ("\n" if file_content.endswith("\n") else "")
    target_path.write_text(new_content, encoding="utf-8")

    failed_stage = _verify_fix(repo_config, settings, workspace.host_path, workspace.run_subdir)
    if failed_stage is not None:
        return (
            None, "verification_failed",
            f"required check '{failed_stage}' failed against the generated fix",
        )

    return _GeneratedFix(new_content=new_content, suggestion=suggestion), None, None


def _find_pull_request(
    db: Any, repository: Repository, diff_snapshot: DiffSnapshot
) -> PullRequest | None:
    """Look up the PR this diff snapshot's push was synced against.

    Prefers the stable `pull_request_id` FK stamped on the snapshot at
    creation time; falls back to matching `PullRequest.head_sha` for
    snapshots created before that column existed. Auto-fix's own model
    call + verification can easily take longer than the next push a
    developer makes - the FK path is what keeps this lookup correct even
    when `PullRequest.head_sha` has since moved on to that newer push.
    """
    if diff_snapshot.pull_request_id is not None:
        return db.get(PullRequest, diff_snapshot.pull_request_id)
    return (
        db.query(PullRequest)
        .filter_by(repository_id=repository.id, head_sha=diff_snapshot.head_sha)
        .one_or_none()
    )


def _persist_attempt(
    db: Any,
    *,
    repository: Repository,
    diff_snapshot: DiffSnapshot,
    finding: AIFinding,
    status: str,
    branch_name: str | None = None,
    pull_request_number: int | None = None,
    pull_request_url: str | None = None,
    error_message: str | None = None,
    trigger: str = "automatic",
    commit_sha: str | None = None,
    actor_login: str | None = None,
) -> AutoFixAttempt:
    attempt = AutoFixAttempt(
        repository_id=repository.id,
        diff_snapshot_id=diff_snapshot.id,
        ai_finding_id=finding.id,
        trigger=trigger,
        status=status,
        branch_name=branch_name,
        pull_request_number=pull_request_number,
        pull_request_url=pull_request_url,
        commit_sha=commit_sha,
        actor_login=actor_login,
        error_message=error_message,
    )
    db.add(attempt)
    record_audit_event(
        db,
        action=f"auto_fix_{status}",
        target_type="ai_finding",
        target_id=str(finding.id),
        repository_id=repository.id,
        metadata={
            "diff_snapshot_id": diff_snapshot.id,
            "branch_name": branch_name,
            "pull_request_number": pull_request_number,
            "trigger": trigger,
            "commit_sha": commit_sha,
        },
    )
    try:
        db.commit()
    except IntegrityError:
        # Another worker already attempted this finding - AutoFixAttempt is
        # immutable per ai_finding_id, defer to the existing row.
        db.rollback()
        existing = db.query(AutoFixAttempt).filter_by(ai_finding_id=finding.id).one()
        return existing
    return attempt


def _verify_fix(
    repo_config: RepoConfig, settings: Settings, workspace_host_path: Path, run_subdir: str
) -> str | None:
    """Run every configured/built-in deterministic check against the
    modified workspace, exactly as the real pipeline does (`app.analysis.
    pipeline.run_analysis_pipeline`), but speculatively: nothing here is
    persisted as a ToolRun, since this isn't evidence about the real diff
    snapshot - it's a verification gate for a not-yet-pushed fix.

    Returns None if every required stage passed, else the name of the first
    required stage that didn't.
    """
    stages = build_all_stages(repo_config, settings, workspace_host_path)
    runner = DockerCliSandboxRunner(
        docker_binary=settings.analysis_docker_binary, volume_name=settings.analysis_volume_name
    )
    for stage in stages:
        if stage.skip_reason is not None:
            continue
        assert stage.limits is not None
        raw_result = runner.run(
            image=stage.image, command=stage.command, run_subdir=run_subdir, limits=stage.limits
        )
        normalized = normalize_result(stage, raw_result)
        if stage.required and normalized.conclusion != "passed":
            return stage.name
    return None


def _generate_suggestion(
    model: ReviewModel, system: str, user: str
) -> tuple[FixSuggestion | None, str | None]:
    try:
        response = model.generate(
            system=system,
            messages=[{"role": "user", "content": user}],
            response_schema=FixSuggestion.model_json_schema(),
        )
    except Exception as exc:  # a provider bug must never crash the pipeline
        logger.exception("auto-fix model call raised unexpectedly")
        return None, str(exc)

    if response.error is not None:
        return None, response.error

    suggestion, errors = validate_fix_suggestion(response.content)
    if suggestion is None:
        return None, "; ".join(errors)
    return suggestion, None


def attempt_fix(
    db: Any,
    client: GitHubClient,
    repository: Repository,
    diff_snapshot: DiffSnapshot,
    finding: AIFinding,
    repo_config: RepoConfig,
    settings: Settings,
) -> AutoFixAttempt:
    """Generate, verify, and (if verification passes) push a fix-PR for one
    finding. Always returns a persisted AutoFixAttempt and never raises past
    this function - every failure mode (model error, invalid output, failed
    verification, GitHub API error) is recorded as its own status rather
    than propagating and aborting the other findings in this snapshot.
    """
    with workspace_for(client, repository, diff_snapshot.head_sha) as workspace:
        result, failure_status, failure_message = _generate_and_verify_fix(
            repository, finding, repo_config, settings, workspace
        )
        if result is None:
            assert failure_status is not None
            return _persist_attempt(
                db, repository=repository, diff_snapshot=diff_snapshot, finding=finding,
                status=failure_status, error_message=failure_message,
            )
        new_content, suggestion = result.new_content, result.suggestion

        pull_request = _find_pull_request(db, repository, diff_snapshot)
        if pull_request is None:
            return _persist_attempt(
                db, repository=repository, diff_snapshot=diff_snapshot, finding=finding,
                status="error", error_message="no open pull request found for this diff snapshot",
            )

        try:
            branch_name = f"reviewrush-fix/{finding.id}-{diff_snapshot.head_sha[:8]}"
            base_tree = client.get_commit_tree_sha(
                repository.owner, repository.name, diff_snapshot.head_sha
            )
            blob_sha = client.create_blob(repository.owner, repository.name, new_content)
            new_tree = client.create_tree(
                repository.owner, repository.name, base_tree, finding.file, blob_sha
            )
            commit_message = (
                f"fix: {finding.title}\n\n"
                f"Automated fix suggested by ReviewRush for a {finding.severity}/"
                f"{finding.category} finding (#{finding.id}).\n\n{suggestion.explanation}"
            )
            commit_sha = client.create_commit(
                repository.owner, repository.name, commit_message, new_tree, diff_snapshot.head_sha
            )
            client.create_ref(
                repository.owner, repository.name, f"refs/heads/{branch_name}", commit_sha
            )
            pr_body = (
                f"Automated fix for a finding from the ReviewRush review of "
                f"#{pull_request.github_pr_number}.\n\n"
                f"**{finding.title}**\n\n{finding.evidence}\n\n{suggestion.explanation}\n\n"
                "This PR was opened automatically by ReviewRush's AI auto-fix and "
                "re-verified against this repository's own deterministic checks before "
                "being opened. It is not auto-merged - please review it like any other PR."
            )
            created = client.create_pull_request(
                repository.owner, repository.name,
                title=f"fix: {finding.title}", body=pr_body,
                head=branch_name, base=pull_request.head_branch,
            )
        except Exception as exc:
            logger.exception("failed to push auto-fix branch/PR")
            return _persist_attempt(
                db, repository=repository, diff_snapshot=diff_snapshot, finding=finding,
                status="error", error_message=str(exc),
            )

        return _persist_attempt(
            db, repository=repository, diff_snapshot=diff_snapshot, finding=finding,
            status="pr_opened", branch_name=branch_name,
            pull_request_number=created.get("number"), pull_request_url=created.get("html_url"),
        )


def _update_manual_fix_comment(
    client: GitHubClient,
    repository: Repository,
    review_comment: ReviewComment | None,
    current_body: str | None,
    render: Callable[[str], str],
) -> None:
    """Best-effort: reflect the manual-fix outcome back on the checkbox
    comment, by applying `render` (one of `mark_manual_fix_applied`/
    `mark_manual_fix_failed`, partially applied with its own keyword
    argument) to the comment's current body. `current_body` is the body the
    triggering webhook delivered (the live body right after the human
    checked the box) - there is no GitHub API to re-fetch a single review
    comment's body, so this must be threaded through from the webhook
    rather than looked up again here.

    Never allowed to change the AutoFixAttempt outcome this function is
    reporting - a failure here (including `current_body` being unavailable)
    is logged and swallowed, not raised, exactly like every other
    GitHub-side side effect in this module.
    """
    if review_comment is None or current_body is None:
        return
    try:
        client.update_review_comment(
            repository.owner, repository.name, review_comment.github_comment_id,
            render(current_body),
        )
    except Exception:
        logger.exception(
            "failed to update manual-fix checkbox comment",
            extra={
                "repository": repository.full_name,
                "comment_id": review_comment.github_comment_id,
            },
        )


def apply_manual_fix(
    db: Any,
    client: GitHubClient,
    repository: Repository,
    diff_snapshot: DiffSnapshot,
    finding: AIFinding,
    repo_config: RepoConfig,
    settings: Settings,
    *,
    actor_login: str,
    review_comment: ReviewComment | None = None,
    current_comment_body: str | None = None,
) -> AutoFixAttempt:
    """Generate, verify, and (if verification passes) commit a fix directly
    to the reviewed branch for one finding a human explicitly asked for via
    the "Apply this fix" checkbox - see `manual_fix_eligible` for which
    findings are offered it at all.

    One-shot like `attempt_fix`: an existing AutoFixAttempt for this finding
    short-circuits immediately (checked before any model call or workspace
    checkout, not just at the final persist step, so a duplicate webhook
    delivery for the same checkbox click costs nothing). A failed attempt is
    not retried through this same mechanism - see `AutoFixAttempt`'s
    docstring.

    Never raises past this function, same guarantee as `attempt_fix`.
    """
    existing = db.query(AutoFixAttempt).filter_by(ai_finding_id=finding.id).one_or_none()
    if existing is not None:
        return existing

    def _report(render: Callable[[str], str]) -> None:
        _update_manual_fix_comment(client, repository, review_comment, current_comment_body, render)

    pull_request = _find_pull_request(db, repository, diff_snapshot)
    if pull_request is None:
        attempt = _persist_attempt(
            db, repository=repository, diff_snapshot=diff_snapshot, finding=finding,
            status="error", error_message="no open pull request found for this diff snapshot",
            trigger="manual", actor_login=actor_login,
        )
        _report(lambda body: mark_manual_fix_failed(body, reason=attempt.error_message or ""))
        return attempt

    with workspace_for(client, repository, diff_snapshot.head_sha) as workspace:
        target_path = (workspace.host_path / finding.file).resolve()
        original_file_content = (
            target_path.read_text(encoding="utf-8", errors="replace")
            if target_path.is_file()
            else None
        )

        result, failure_status, failure_message = _generate_and_verify_fix(
            repository, finding, repo_config, settings, workspace
        )
        if result is None:
            assert failure_status is not None
            attempt = _persist_attempt(
                db, repository=repository, diff_snapshot=diff_snapshot, finding=finding,
                status=failure_status, error_message=failure_message,
                trigger="manual", actor_login=actor_login,
            )
            _report(
                lambda body: mark_manual_fix_failed(body, reason=failure_message or failure_status)
            )
            return attempt
        new_content, suggestion = result.new_content, result.suggestion

        try:
            live_head_sha = client.get_ref_sha(
                repository.owner, repository.name, pull_request.head_branch
            )
            if live_head_sha is None:
                raise RuntimeError(f"branch {pull_request.head_branch} no longer exists")

            # Guard against clobbering a concurrent edit to this exact file:
            # if its content on the live branch has already drifted from
            # what this finding was reported against, the line range this
            # fix targets may no longer mean what it did at review time -
            # refuse rather than silently overwrite whatever changed it.
            live_content = client.get_file_contents(
                repository.owner, repository.name, finding.file, ref=live_head_sha
            )
            if live_content != original_file_content:
                attempt = _persist_attempt(
                    db, repository=repository, diff_snapshot=diff_snapshot, finding=finding,
                    status="stale_target",
                    error_message=(
                        f"{finding.file} changed on {pull_request.head_branch} since this "
                        "finding was reported - refusing to overwrite it"
                    ),
                    trigger="manual", actor_login=actor_login,
                )
                _report(
                    lambda body: mark_manual_fix_failed(body, reason=attempt.error_message or "")
                )
                return attempt

            base_tree = client.get_commit_tree_sha(repository.owner, repository.name, live_head_sha)
            blob_sha = client.create_blob(repository.owner, repository.name, new_content)
            new_tree = client.create_tree(
                repository.owner, repository.name, base_tree, finding.file, blob_sha
            )
            commit_message = (
                f"fix: {finding.title}\n\n"
                f"Fix requested by @{actor_login} via ReviewRush's \"Apply this fix\" "
                f"checkbox, for a {finding.severity}/{finding.category} finding "
                f"(#{finding.id}).\n\n{suggestion.explanation}"
            )
            commit_sha = client.create_commit(
                repository.owner, repository.name, commit_message, new_tree, live_head_sha
            )
            client.update_branch_ref(
                repository.owner, repository.name, pull_request.head_branch, commit_sha
            )
        except Exception as exc:
            logger.exception("failed to commit manual fix")
            error_message = str(exc)
            attempt = _persist_attempt(
                db, repository=repository, diff_snapshot=diff_snapshot, finding=finding,
                status="error", error_message=error_message, trigger="manual",
                actor_login=actor_login,
            )
            _report(lambda body: mark_manual_fix_failed(body, reason=error_message))
            return attempt

        attempt = _persist_attempt(
            db, repository=repository, diff_snapshot=diff_snapshot, finding=finding,
            status="committed", commit_sha=commit_sha, trigger="manual", actor_login=actor_login,
        )
        _report(lambda body: mark_manual_fix_applied(body, commit_sha=commit_sha))
        return attempt


def run_manual_fix(
    db: Any,
    client: GitHubClient,
    repository: Repository,
    diff_snapshot: DiffSnapshot,
    finding: AIFinding,
    review_comment: ReviewComment | None,
    actor_login: str,
    current_comment_body: str,
) -> AutoFixAttempt | None:
    """Entry point for the manual-fix task: re-validates eligibility fresh
    (never trusts that a rendered checkbox is still valid - config may have
    changed since) before calling `apply_manual_fix`. Returns None (no-op,
    no AutoFixAttempt row) when auto-fix is disabled globally, disabled for
    this repo, or the finding no longer qualifies for the manual path.
    """
    settings = get_settings()
    config_yaml = client.get_file_contents(
        repository.owner, repository.name, REPO_CONFIG_PATH, ref=diff_snapshot.head_sha
    )
    repo_config = parse_repo_config(config_yaml)
    if not manual_fix_eligible(finding, repo_config, settings):
        return None
    return apply_manual_fix(
        db, client, repository, diff_snapshot, finding, repo_config, settings,
        actor_login=actor_login, review_comment=review_comment,
        current_comment_body=current_comment_body,
    )


def run_auto_fix_for_snapshot(
    db: Any, client: GitHubClient, repository: Repository, diff_snapshot: DiffSnapshot
) -> list[AutoFixAttempt]:
    """Entry point for the auto-fix task: resolves eligibility for every
    finding on this snapshot's completed AIReview and attempts a fix for
    each. Returns an empty list (no-op) when auto-fix is disabled globally,
    disabled for this repo, or there's no completed AIReview to draw
    findings from - mirrors every other stage's disabled-feature short-circuit.
    """
    settings = get_settings()
    if not settings.autofix_enabled:
        return []

    config_yaml = client.get_file_contents(
        repository.owner, repository.name, REPO_CONFIG_PATH, ref=diff_snapshot.head_sha
    )
    repo_config = parse_repo_config(config_yaml)
    if not repo_config.auto_fix.enabled:
        return []

    ai_review = db.query(AIReview).filter_by(diff_snapshot_id=diff_snapshot.id).one_or_none()
    if ai_review is None or ai_review.status != "completed":
        return []

    findings = eligible_findings(db, ai_review, repo_config, settings)
    return [
        attempt_fix(db, client, repository, diff_snapshot, finding, repo_config, settings)
        for finding in findings
    ]
