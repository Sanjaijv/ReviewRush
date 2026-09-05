import logging
from typing import Any

from sqlalchemy.exc import IntegrityError

from app.autofix.service import manual_fix_eligible
from app.checks.fingerprint import SUMMARY_FINGERPRINT, finding_fingerprint, meets_inline_threshold
from app.checks.rendering import (
    check_conclusion,
    check_title,
    mark_outdated,
    render_inline_comment_body,
    render_summary_markdown,
)
from app.config import get_settings
from app.diffs.patch import map_added_lines
from app.github.auth import get_installation_access_token
from app.github.client import GitHubClient
from app.models import (
    AIFinding,
    AIReview,
    DiffSnapshot,
    PolicyDecision,
    PullRequest,
    Repository,
    ReviewComment,
    ToolRun,
)
from app.repo_config import RepoConfig, parse_repo_config

logger = logging.getLogger(__name__)

REPO_CONFIG_PATH = ".reviewrush.yml"


def start_check_run(
    client: GitHubClient, repository: Repository, diff_snapshot: DiffSnapshot, db: Any
) -> None:
    """Create the in-progress Check Run for this head_sha, at review start.

    Best-effort: a failure here must not break the analysis pipeline that
    triggered it. `run_github_checks_for_snapshot` creates a check run on the
    fly at completion time if this never ran or failed.
    """
    if diff_snapshot.github_check_run_id is not None:
        return
    settings = get_settings()
    try:
        check_run = client.create_check_run(
            repository.owner, repository.name, settings.checks_run_name, diff_snapshot.head_sha
        )
        check_run_id = check_run.get("id") if isinstance(check_run, dict) else None
        if not isinstance(check_run_id, int):
            raise ValueError(f"unexpected create_check_run response: {check_run!r}")
        diff_snapshot.github_check_run_id = check_run_id
        db.commit()
    except Exception:
        logger.exception(
            "failed to create in-progress check run",
            extra={"repository": repository.full_name, "head_sha": diff_snapshot.head_sha},
        )
        db.rollback()


def _complete_check_run(
    client: GitHubClient,
    repository: Repository,
    diff_snapshot: DiffSnapshot,
    db: Any,
    decision: PolicyDecision,
) -> None:
    conclusion = check_conclusion(decision.decision)
    title = check_title(decision)
    summary = f"{len(decision.reasons)} reason(s): " + "; ".join(decision.reasons[:3])

    if diff_snapshot.github_check_run_id is None:
        check_run = client.create_check_run(
            repository.owner,
            repository.name,
            get_settings().checks_run_name,
            diff_snapshot.head_sha,
            conclusion=conclusion,
            title=title,
            summary=summary,
        )
        diff_snapshot.github_check_run_id = check_run["id"]
        db.commit()
        return

    client.update_check_run(
        repository.owner,
        repository.name,
        diff_snapshot.github_check_run_id,
        conclusion=conclusion,
        title=title,
        summary=summary,
    )


def _find_pull_request(
    db: Any, repository: Repository, diff_snapshot: DiffSnapshot
) -> PullRequest | None:
    """Look up the PR this diff snapshot's push was synced against.

    Prefers the stable `pull_request_id` FK stamped on the snapshot at
    creation time; falls back to matching `PullRequest.head_sha` for
    snapshots created before that column existed. The FK path is immune to
    the race where a newer push has since moved `PullRequest.head_sha` on
    before this (potentially slow) stage got to run - the head_sha fallback
    is not, and can wrongly come up empty for a PR that is very much still
    open.
    """
    if diff_snapshot.pull_request_id is not None:
        return db.get(PullRequest, diff_snapshot.pull_request_id)
    return (
        db.query(PullRequest)
        .filter_by(repository_id=repository.id, head_sha=diff_snapshot.head_sha)
        .one_or_none()
    )


def _existing_comment(
    db: Any, pull_request: PullRequest, kind: str, fingerprint: str
) -> ReviewComment | None:
    return (
        db.query(ReviewComment)
        .filter_by(pull_request_id=pull_request.id, kind=kind, fingerprint=fingerprint)
        .one_or_none()
    )


def _upsert_review_comment(
    db: Any,
    *,
    repository: Repository,
    pull_request: PullRequest,
    diff_snapshot: DiffSnapshot,
    ai_finding_id: int | None,
    kind: str,
    fingerprint: str,
    github_comment_id: int,
    github_node_id: str | None,
    path: str | None,
    line: int | None,
) -> None:
    row = _existing_comment(db, pull_request, kind, fingerprint)
    if row is None:
        row = ReviewComment(
            repository_id=repository.id,
            pull_request_id=pull_request.id,
            diff_snapshot_id=diff_snapshot.id,
            ai_finding_id=ai_finding_id,
            kind=kind,
            fingerprint=fingerprint,
            github_comment_id=github_comment_id,
            github_node_id=github_node_id,
            path=path,
            line=line,
            status="posted",
            head_sha=diff_snapshot.head_sha,
        )
        db.add(row)
    else:
        row.diff_snapshot_id = diff_snapshot.id
        row.github_comment_id = github_comment_id
        row.github_node_id = github_node_id
        row.status = "posted"
        row.head_sha = diff_snapshot.head_sha
    try:
        db.commit()
    except IntegrityError:
        # Another worker already posted this exact (pull_request, kind,
        # fingerprint) comment - the unique constraint is what actually
        # prevents the duplicate; this just avoids crashing the task.
        db.rollback()


def _post_or_update_summary(
    client: GitHubClient,
    db: Any,
    repository: Repository,
    pull_request: PullRequest,
    diff_snapshot: DiffSnapshot,
    body: str,
) -> None:
    existing = _existing_comment(db, pull_request, "summary", SUMMARY_FINGERPRINT)
    if existing is not None:
        client.update_issue_comment(
            repository.owner, repository.name, existing.github_comment_id, body
        )
        existing.diff_snapshot_id = diff_snapshot.id
        existing.head_sha = diff_snapshot.head_sha
        db.commit()
        return

    comment = client.create_issue_comment(
        repository.owner, repository.name, pull_request.github_pr_number, body
    )
    _upsert_review_comment(
        db,
        repository=repository,
        pull_request=pull_request,
        diff_snapshot=diff_snapshot,
        ai_finding_id=None,
        kind="summary",
        fingerprint=SUMMARY_FINGERPRINT,
        github_comment_id=comment["id"],
        github_node_id=comment.get("node_id"),
        path=None,
        line=None,
    )


def _post_inline_comments(
    client: GitHubClient,
    db: Any,
    repository: Repository,
    pull_request: PullRequest,
    diff_snapshot: DiffSnapshot,
    findings: list[AIFinding],
    settings: Any,
    repo_config: RepoConfig,
) -> set[int]:
    """Post inline comments for eligible findings, capped and thresholded to
    keep noise down. Returns the ids of findings that got an inline comment
    (everything else stays summary-only), per the fallback requirement.
    """
    posted_finding_ids: set[int] = set()
    if not findings:
        return posted_finding_ids

    position_by_path: dict[str, dict[int, int]] = {}
    for changed_file in diff_snapshot.changed_files:
        path = changed_file.new_path or changed_file.old_path
        if path and changed_file.patch and not changed_file.content_fetched:
            position_by_path[path] = map_added_lines(changed_file.patch)

    posted_count = 0
    for finding in findings:
        if posted_count >= settings.checks_max_inline_comments:
            break
        if not meets_inline_threshold(finding.severity, settings.checks_min_inline_severity):
            continue

        fingerprint = finding_fingerprint(finding)
        existing = _existing_comment(db, pull_request, "inline", fingerprint)
        if existing is not None:
            posted_finding_ids.add(finding.id)
            continue

        positions = position_by_path.get(finding.file, {})
        position = positions.get(finding.start_line)
        if position is None:
            # Can't attach to this line - fall back to summary-only listing.
            continue

        try:
            comment = client.create_review_comment(
                repository.owner,
                repository.name,
                pull_request.github_pr_number,
                commit_id=diff_snapshot.head_sha,
                path=finding.file,
                position=position,
                body=render_inline_comment_body(
                    finding,
                    offer_manual_fix=manual_fix_eligible(finding, repo_config, settings),
                ),
            )
        except Exception:
            logger.exception(
                "failed to post inline review comment",
                extra={"repository": repository.full_name, "file": finding.file},
            )
            continue

        _upsert_review_comment(
            db,
            repository=repository,
            pull_request=pull_request,
            diff_snapshot=diff_snapshot,
            ai_finding_id=finding.id,
            kind="inline",
            fingerprint=fingerprint,
            github_comment_id=comment["id"],
            github_node_id=comment.get("node_id"),
            path=finding.file,
            line=finding.start_line,
        )
        posted_finding_ids.add(finding.id)
        posted_count += 1

    return posted_finding_ids


def _mark_stale_comments_outdated(
    client: GitHubClient,
    db: Any,
    repository: Repository,
    pull_request: PullRequest,
    current_fingerprints: set[str],
) -> None:
    """A finding that was posted for an earlier head_sha but no longer
    appears in the current AIReview has had its underlying code change -
    edit its comment to say so, and collapse it via the GraphQL
    `minimizeComment` mutation so it no longer shows expanded on the PR by
    default on the next push. Editing the body alone (the REST API's only
    option) left a resolved finding fully visible until a human manually
    clicked "Resolve conversation" - minimizing is what actually keeps only
    current findings visible without that manual step.

    Both calls are best-effort and independent: a comment predating the
    `github_node_id` column (or a `minimizeComment` failure) still gets its
    body edited, matching the pre-existing behavior, even though it won't
    collapse.
    """
    stale = (
        db.query(ReviewComment)
        .filter_by(pull_request_id=pull_request.id, kind="inline", status="posted")
        .all()
    )
    for row in stale:
        if row.fingerprint in current_fingerprints:
            continue
        body = mark_outdated(_comment_body_placeholder())
        try:
            client.update_review_comment(
                repository.owner, repository.name, row.github_comment_id, body
            )
        except Exception:
            logger.exception(
                "failed to mark review comment outdated",
                extra={"repository": repository.full_name, "comment_id": row.github_comment_id},
            )
            continue
        row.status = "outdated"

        if row.github_node_id:
            try:
                client.minimize_comment(row.github_node_id, classifier="OUTDATED")
            except Exception:
                logger.exception(
                    "failed to minimize outdated review comment",
                    extra={
                        "repository": repository.full_name,
                        "comment_id": row.github_comment_id,
                    },
                )
    db.commit()


def _comment_body_placeholder() -> str:
    # GitHub's API has no "fetch current body" round trip we want to spend on
    # this path, so the outdated marker is prefixed onto a short fixed note
    # rather than the (unknown-to-us) live body text.
    return "This finding is no longer present in the latest review."


def run_github_checks_for_snapshot(
    db: Any, repository: Repository, diff_snapshot: DiffSnapshot
) -> None:
    """Publish Phase 8 review results for one immutable diff snapshot: complete
    the Check Run, post/update the one PR summary comment, and post inline
    comments for eligible findings - idempotently, keyed by finding fingerprint.
    """
    decision = db.query(PolicyDecision).filter_by(diff_snapshot_id=diff_snapshot.id).one_or_none()
    if decision is None:
        logger.warning(
            "no policy decision found for diff snapshot, skipping checks/comments",
            extra={"repository": repository.full_name, "head_sha": diff_snapshot.head_sha},
        )
        return

    settings = get_settings()
    installation = repository.installation
    token = get_installation_access_token(installation.github_installation_id)

    ai_review = db.query(AIReview).filter_by(diff_snapshot_id=diff_snapshot.id).one_or_none()
    tool_runs = db.query(ToolRun).filter_by(diff_snapshot_id=diff_snapshot.id).all()
    findings = list(ai_review.findings) if ai_review is not None else []

    with GitHubClient(token) as client:
        _complete_check_run(client, repository, diff_snapshot, db, decision)

        pull_request = _find_pull_request(db, repository, diff_snapshot)
        if pull_request is None:
            logger.info(
                "no open pull request for this head_sha, skipping summary/inline comments",
                extra={"repository": repository.full_name, "head_sha": diff_snapshot.head_sha},
            )
            return

        config_yaml = client.get_file_contents(
            repository.owner, repository.name, REPO_CONFIG_PATH, ref=diff_snapshot.head_sha
        )
        repo_config = parse_repo_config(config_yaml)

        inline_posted_ids: set[int] = set()
        if repo_config.review.post_inline_comments:
            inline_posted_ids = _post_inline_comments(
                client, db, repository, pull_request, diff_snapshot, findings, settings,
                repo_config,
            )
            current_fingerprints = {finding_fingerprint(f) for f in findings}
            _mark_stale_comments_outdated(
                client, db, repository, pull_request, current_fingerprints
            )

        summary_body = render_summary_markdown(
            decision=decision,
            ai_review=ai_review,
            tool_runs=tool_runs,
            findings=findings,
            inline_posted_findings=inline_posted_ids,
            head_sha=diff_snapshot.head_sha,
        )
        _post_or_update_summary(client, db, repository, pull_request, diff_snapshot, summary_body)

    logger.info(
        "published github checks and comments",
        extra={
            "repository": repository.full_name,
            "head_sha": diff_snapshot.head_sha,
            "decision": decision.decision,
        },
    )
