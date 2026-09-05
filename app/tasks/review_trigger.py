"""Builds an immutable diff snapshot for one commit and queues the
deterministic analysis pipeline against it.

Shared by `app.tasks.github_webhook`'s push handler and any other code path
that pushes a commit itself and therefore won't get a push webhook it can
act on. `_handle_push` intentionally ignores any bot-authored push (to avoid
an automation loop) - which means a commit ReviewRush pushes on its own
behalf (e.g. `app.autofix.service.apply_manual_fix` committing directly to
the reviewed branch) needs to trigger its own review explicitly, exactly
the same way a human's push would have, rather than relying on that guarded
webhook path.
"""

import logging
from typing import Any

from app.checks.service import start_check_run
from app.diffs.service import build_diff_snapshot
from app.github.client import GitHubClient
from app.models import DiffSnapshot, MergeAttempt, PullRequest, Repository

logger = logging.getLogger(__name__)


def supersede_previous_snapshots(
    db: Any, repository: Repository, new_snapshot: DiffSnapshot
) -> None:
    """Automatically cancel every other still-active DiffSnapshot for this
    repository now that a newer commit has produced its own snapshot (Phase
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


def trigger_review_for_commit(
    db: Any,
    client: GitHubClient,
    repository: Repository,
    target_branch: str,
    head_sha: str,
    pull_request: PullRequest | None,
) -> DiffSnapshot | None:
    """Build the immutable diff snapshot for `head_sha` and queue the
    deterministic analysis pipeline against it. Returns None (no-op) if
    `target_branch` has no head to compare against.

    Uses the target branch's current head as the comparison base - if that
    branch moves before the compare call resolves, GitHub's merge-base
    comparison still returns a valid (if slightly stale) merge-base, and the
    snapshot itself is keyed to the immutable head_sha regardless.
    """
    # Deferred: app.tasks.analysis pulls in the full task chain (ai_review ->
    # policy -> checks -> autofix), which imports this module - importing it
    # at module level here would be circular for any caller that reaches
    # this module through that same chain (e.g. app.tasks.autofix).
    from app.tasks.analysis import run_analysis_pipeline_task

    base_sha = client.get_ref_sha(repository.owner, repository.name, target_branch)
    if base_sha is None:
        logger.warning(
            "target branch has no head, skipping diff snapshot",
            extra={"repository": repository.full_name, "target_branch": target_branch},
        )
        return None

    snapshot = build_diff_snapshot(
        db=db,
        client=client,
        repository=repository,
        base_sha=base_sha,
        head_sha=head_sha,
        pull_request_id=pull_request.id if pull_request is not None else None,
    )
    supersede_previous_snapshots(db, repository, snapshot)
    # Best-effort: an in-progress Check Run at review start (Phase 8) so the
    # PR shows review activity immediately. Its absence never blocks the
    # pipeline - the checks task creates one on the fly at completion time.
    start_check_run(client, repository, snapshot, db)
    run_analysis_pipeline_task.delay(repository.id, snapshot.id)
    return snapshot
