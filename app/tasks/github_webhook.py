import logging
from datetime import UTC, datetime
from typing import Any

from app.celery_app import celery_app
from app.checks.service import start_check_run
from app.context.service import purge_repository_index
from app.dashboard.audit import record_audit_event
from app.db import SessionLocal
from app.diffs.service import build_diff_snapshot
from app.github.auth import get_installation_access_token
from app.github.client import GitHubClient
from app.github.pr_automation import resolve_branches, sync_pull_request_for_push
from app.locking import LockNotAcquired, repository_lock
from app.models import DiffSnapshot, Installation, MergeAttempt, Repository, WebhookDelivery
from app.repo_config import parse_repo_config
from app.tasks._reliability import handle_task_failure
from app.tasks.analysis import run_analysis_pipeline_task
from app.tenancy.plans import resolve_limits
from app.tenancy.provisioning import get_or_create_organization

logger = logging.getLogger(__name__)

REPO_CONFIG_PATH = ".reviewrush.yml"


def _mark_delivery(db: Any, delivery_id: str, status: str) -> None:
    delivery = db.query(WebhookDelivery).filter_by(delivery_id=delivery_id).one_or_none()
    if delivery is None:
        return
    delivery.status = status
    delivery.processed_at = datetime.now(UTC)
    db.commit()


def _add_repositories(db: Any, installation: Installation, repo_payloads: list[dict]) -> None:
    """Upsert Repository rows for one installation from a list of GitHub
    repository payloads (`{id, full_name, ...}`), applying the Phase 17 plan
    repository-count limit. Shared by every event that can add repositories
    to an installation - both `installation_repositories.added` and an
    `installation` event's own `repositories` field (present when repos were
    selected at install time, which is the *first* time an app sees them and
    therefore the case that matters most for a repo actually getting
    registered).
    """
    if not repo_payloads:
        return

    organization = get_or_create_organization(db, installation)
    limits = resolve_limits(organization)

    for repo_payload in repo_payloads:
        github_repo_id = repo_payload.get("id")
        repository = db.query(Repository).filter_by(github_repo_id=github_repo_id).one_or_none()
        full_name = repo_payload.get("full_name", "")
        owner, _, name = full_name.partition("/")

        # Plan repository-count enforcement (Phase 17). A repo beyond the
        # organization's plan limit is still recorded (so it shows up in the
        # dashboard as "connected but inactive, upgrade to enable") but left
        # `is_active=False` - it never runs deterministic checks, AI review,
        # or auto-merge, the same inert state a manually disconnected repo
        # is in. This never touches required-check flags or the policy/merge
        # gate for repos that *are* active - see app/ai/service.py.
        active_count = (
            db.query(Repository)
            .filter_by(installation_id=installation.id, is_active=True)
            .count()
        )
        within_plan = limits.max_repositories is None or active_count < limits.max_repositories

        if repository is None:
            repository = Repository(
                installation_id=installation.id,
                github_repo_id=github_repo_id,
                owner=owner,
                name=name,
                full_name=full_name,
                is_active=within_plan,
            )
            db.add(repository)
        else:
            repository.is_active = within_plan
            repository.installation_id = installation.id

        if not within_plan:
            db.flush()
            record_audit_event(
                db,
                action="repository.plan_limit_blocked",
                target_type="repository",
                target_id=str(repository.id),
                repository_id=repository.id,
                metadata={"plan": organization.plan, "max_repositories": limits.max_repositories},
            )


def _handle_installation(db: Any, payload: dict) -> None:
    action = payload.get("action")
    installation_payload = payload.get("installation") or {}
    github_installation_id = installation_payload.get("id")
    account = installation_payload.get("account") or {}

    installation = (
        db.query(Installation)
        .filter_by(github_installation_id=github_installation_id)
        .one_or_none()
    )

    if action == "deleted":
        if installation is not None:
            installation.status = "deleted"
            repository_ids = []
            for repository in installation.repositories:
                repository.is_active = False
                repository_ids.append(repository.id)
            purge_repository_index(db, repository_ids)
            db.commit()
        return

    is_new_installation = installation is None
    if installation is None:
        installation = Installation(
            github_installation_id=github_installation_id,
            account_login=account.get("login", ""),
            account_type=account.get("type", ""),
            status="active",
        )
        db.add(installation)
        db.flush()
        get_or_create_organization(db, installation)
    else:
        installation.account_login = account.get("login", installation.account_login)
        installation.account_type = account.get("type", installation.account_type)
        installation.status = "suspended" if action == "suspend" else "active"

    if action == "created" and is_new_installation:
        # The `repositories` field is only present when repository_selection
        # is "selected" - GitHub omits it for "all" (an account could have
        # thousands of repos) and expects the app to call the installation
        # repositories API instead. Without this, a repo chosen at install
        # time never gets a Repository row until it's later removed and
        # re-added via the installation settings, which is the bug this
        # branch fixes.
        if installation_payload.get("repository_selection") == "all" and github_installation_id:
            token = get_installation_access_token(github_installation_id)
            with GitHubClient(token) as client:
                _add_repositories(db, installation, client.list_installation_repositories())
        else:
            _add_repositories(db, installation, payload.get("repositories", []))

    db.commit()


def _handle_installation_repositories(db: Any, payload: dict) -> None:
    installation_payload = payload.get("installation") or {}
    github_installation_id = installation_payload.get("id")

    installation = (
        db.query(Installation)
        .filter_by(github_installation_id=github_installation_id)
        .one_or_none()
    )
    if installation is None:
        logger.warning(
            "installation_repositories event for unknown installation",
            extra={"github_installation_id": github_installation_id},
        )
        return

    _add_repositories(db, installation, payload.get("repositories_added", []))

    removed_repository_ids: list[int] = []
    for repo_payload in payload.get("repositories_removed", []):
        github_repo_id = repo_payload.get("id")
        repository = db.query(Repository).filter_by(github_repo_id=github_repo_id).one_or_none()
        if repository is not None:
            repository.is_active = False
            removed_repository_ids.append(repository.id)

    purge_repository_index(db, removed_repository_ids)
    db.commit()


def _handle_push(db: Any, payload: dict) -> None:
    ref = payload.get("ref") or ""
    if not ref.startswith("refs/heads/"):
        return
    branch = ref.removeprefix("refs/heads/")

    sender = payload.get("sender") or {}
    if sender.get("type") == "Bot":
        logger.info("ignoring push from a bot sender to avoid automation loops")
        return

    installation_payload = payload.get("installation") or {}
    github_installation_id = installation_payload.get("id")
    repository_payload = payload.get("repository") or {}
    github_repo_id = repository_payload.get("id")

    repository = db.query(Repository).filter_by(github_repo_id=github_repo_id).one_or_none()
    if repository is None or not repository.is_active:
        logger.warning(
            "push event for unknown or inactive repository",
            extra={"github_repo_id": github_repo_id},
        )
        return

    if not github_installation_id:
        logger.warning(
            "push event missing installation id", extra={"repository": repository.full_name}
        )
        return

    if payload.get("deleted"):
        logger.info(
            "branch deleted, skipping PR automation",
            extra={"repository": repository.full_name, "branch": branch},
        )
        return

    head_sha = payload.get("after")
    if not head_sha:
        return

    token = get_installation_access_token(github_installation_id)
    with GitHubClient(token) as client:
        config_yaml = client.get_file_contents(
            repository.owner, repository.name, REPO_CONFIG_PATH, ref=branch
        )
        repo_config = parse_repo_config(config_yaml)
        source_branch, target_branch = resolve_branches(repository, repo_config)

        if branch != source_branch:
            return

        commits = payload.get("commits") or []
        # Concurrency lock (Phase 13): two overlapping pushes (or a
        # duplicate/retried webhook delivery) for the same repository must
        # never race the "list open PRs, then create if none exists" check
        # in sync_pull_request_for_push - that race is exactly how a
        # duplicate PR would get created.
        try:
            with repository_lock(f"pr-sync:{repository.id}"):
                sync_pull_request_for_push(
                    db=db,
                    client=client,
                    repository=repository,
                    source_branch=source_branch,
                    target_branch=target_branch,
                    head_sha=head_sha,
                    commits=commits,
                )
        except LockNotAcquired:
            logger.info(
                "pr-sync lock contended, skipping this push",
                extra={"repository": repository.full_name, "head_sha": head_sha},
            )
            return

        _trigger_analysis(db, client, repository, target_branch, head_sha)


def _trigger_analysis(
    db: Any, client: GitHubClient, repository: Repository, target_branch: str, head_sha: str
) -> None:
    """Build the immutable diff snapshot for this push and queue the
    deterministic analysis pipeline against it.

    Uses the target branch's current head as the comparison base - if that
    branch moves before the compare call resolves, GitHub's merge-base
    comparison still returns a valid (if slightly stale) merge-base, and the
    snapshot itself is keyed to the immutable head_sha regardless.
    """
    base_sha = client.get_ref_sha(repository.owner, repository.name, target_branch)
    if base_sha is None:
        logger.warning(
            "target branch has no head, skipping diff snapshot",
            extra={"repository": repository.full_name, "target_branch": target_branch},
        )
        return

    snapshot = build_diff_snapshot(
        db=db,
        client=client,
        repository=repository,
        base_sha=base_sha,
        head_sha=head_sha,
    )
    _supersede_previous_snapshots(db, repository, snapshot)
    # Best-effort: an in-progress Check Run at review start (Phase 8) so the
    # PR shows review activity immediately. Its absence never blocks the
    # pipeline - the checks task creates one on the fly at completion time.
    start_check_run(client, repository, snapshot, db)
    run_analysis_pipeline_task.delay(repository.id, snapshot.id)


def _supersede_previous_snapshots(
    db: Any, repository: Repository, new_snapshot: DiffSnapshot
) -> None:
    """Automatically cancel every other still-active DiffSnapshot for this
    repository now that a newer push has produced its own snapshot (Phase
    13 graceful cancellation).

    Every pipeline task stage already checks `status == "cancelled"` before
    starting new work (see app/tasks/analysis.py et al.) and no-ops if so -
    this is what makes marking a run cancelled here actually stop it from
    doing further wasted work, without needing to kill anything already
    in-flight. Manual cancellation from the dashboard (app/dashboard/control.py)
    remains available for a run this doesn't catch, e.g. a second PR/branch.

    Excludes any snapshot with a successful MergeAttempt: a commit that has
    already been merged is a permanent fact, never something a later push
    "supersedes" - marking it cancelled after the fact would corrupt the
    audit trail for no reason.
    """
    already_merged_ids = db.query(MergeAttempt.diff_snapshot_id).filter(
        MergeAttempt.repository_id == repository.id, MergeAttempt.outcome == "merged"
    )
    stale_snapshots = (
        db.query(DiffSnapshot)
        .filter(
            DiffSnapshot.repository_id == repository.id,
            DiffSnapshot.id != new_snapshot.id,
            DiffSnapshot.status == "complete",
            DiffSnapshot.id.notin_(already_merged_ids),
        )
        .all()
    )
    if not stale_snapshots:
        return
    for stale in stale_snapshots:
        stale.status = "cancelled"
        logger.info(
            "review run superseded by a newer push, auto-cancelled",
            extra={
                "repository": repository.full_name,
                "head_sha": stale.head_sha,
                "superseded_by": new_snapshot.head_sha,
            },
        )
    db.commit()


_HANDLERS = {
    "installation": _handle_installation,
    "installation_repositories": _handle_installation_repositories,
    "push": _handle_push,
}


@celery_app.task(name="reviewrush.process_github_webhook", bind=True)
def process_github_webhook(self: Any, delivery_id: str, event_type: str, payload: dict) -> str:
    """Route one verified, deduplicated webhook delivery to its handler.

    Events without a dedicated handler (push, pull_request, pull_request_review,
    check_run, check_suite) are only acknowledged here — handling them is later phases.
    """
    db = SessionLocal()
    try:
        handler = _HANDLERS.get(event_type)
        if handler is not None:
            handler(db, payload)
        _mark_delivery(db, delivery_id, "processed")
        return "processed"
    except Exception as exc:
        logger.exception(
            "github webhook processing failed",
            extra={"delivery_id": delivery_id, "event_type": event_type},
        )
        db.rollback()
        handle_task_failure(
            self,
            exc,
            task_name="reviewrush.process_github_webhook",
            args=(delivery_id, event_type, payload),
        )
        _mark_delivery(db, delivery_id, "failed")
        return "failed"
    finally:
        db.close()
