import logging
from typing import Any

from app.context.service import purge_repository_index
from app.dashboard.audit import record_audit_event
from app.models import (
    AIFinding,
    AIReview,
    ChangedFile,
    DiffSnapshot,
    EscapedDefect,
    FindingFeedback,
    MergeAttempt,
    Organization,
    PolicyDecision,
    RepoContextSnapshot,
    Repository,
    ReviewComment,
    SpecializedReview,
    ToolRun,
)

logger = logging.getLogger(__name__)


def _repository_ids(db: Any, organization: Organization) -> list[int]:
    return [
        r.id
        for r in db.query(Repository)
        .filter_by(installation_id=organization.installation_id)
        .all()
    ]


def delete_organization_data(
    db: Any, organization: Organization, *, actor_user_id: int, actor_login: str
) -> dict[str, int]:
    """Permanently delete all retained review evidence for an Organization's
    repositories (Phase 17 acceptance criterion: "an organization can ...
    delete its retained data").

    Deletes child rows before parents (no DB-level ON DELETE CASCADE exists
    for most of these tables - see the individual model docstrings) but
    deliberately leaves `Repository`/`PullRequest`/`Installation` rows and
    `AuditEvent`/`RepositoryConfigVersion` intact: this purges *evidence*
    (reviews, findings, diffs, checks, comments, merge history, feedback),
    not the account structure or the immutable audit trail Section 7
    requires - the audit event recording that this deletion happened is
    written *before* anything is removed, specifically so it survives the
    purge it describes.
    """
    repository_ids = _repository_ids(db, organization)

    record_audit_event(
        db,
        action="organization.data_deleted",
        target_type="organization",
        target_id=str(organization.id),
        actor_type="user",
        actor_user_id=actor_user_id,
        actor_login=actor_login,
        metadata={"repository_count": len(repository_ids)},
    )

    if not repository_ids:
        db.commit()
        return {"repositories": 0}

    counts: dict[str, int] = {"repositories": len(repository_ids)}

    def _delete(model: Any, label: str) -> None:
        counts[label] = (
            db.query(model)
            .filter(model.repository_id.in_(repository_ids))
            .delete(synchronize_session=False)
        )

    _delete(FindingFeedback, "finding_feedback")
    _delete(EscapedDefect, "escaped_defects")
    _delete(ReviewComment, "review_comments")
    _delete(SpecializedReview, "specialized_reviews")
    _delete(AIFinding, "ai_findings")
    _delete(AIReview, "ai_reviews")
    _delete(PolicyDecision, "policy_decisions")
    _delete(MergeAttempt, "merge_attempts")
    _delete(ToolRun, "tool_runs")
    _delete(RepoContextSnapshot, "repo_context_snapshots")

    # ChangedFile has no DB-level ON DELETE CASCADE from diff_snapshots (only
    # the ORM relationship declares cascade="all, delete-orphan", which a
    # bulk .delete() bypasses) - delete it explicitly first or the
    # DiffSnapshot delete below violates the foreign key.
    diff_snapshot_ids = [
        row.id
        for row in db.query(DiffSnapshot.id)
        .filter(DiffSnapshot.repository_id.in_(repository_ids))
        .all()
    ]
    if diff_snapshot_ids:
        counts["changed_files"] = (
            db.query(ChangedFile)
            .filter(ChangedFile.diff_snapshot_id.in_(diff_snapshot_ids))
            .delete(synchronize_session=False)
        )
    _delete(DiffSnapshot, "diff_snapshots")

    purge_repository_index(db, repository_ids)

    db.commit()
    logger.info(
        "organization data deleted",
        extra={"organization_id": organization.id, "counts": counts},
    )
    return counts
