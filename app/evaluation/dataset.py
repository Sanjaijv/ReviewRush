from sqlalchemy import func
from sqlalchemy.orm import Session

from app.evaluation.redaction import pseudonymize_repository_ref, redact_text
from app.models import (
    AIFinding,
    AIReview,
    DiffSnapshot,
    EvalDatasetItem,
    EvalDatasetVersion,
    FindingFeedback,
    Repository,
)


def build_dataset_version(
    db: Session, *, actor_user_id: int, actor_login: str, notes: str = ""
) -> EvalDatasetVersion:
    """Build a new versioned, de-identified evaluation dataset snapshot
    (Phase 15) from every AIFinding with consented, confirmed developer
    feedback attached.

    Only feedback with `consent=True` and `reaction="useful"` is included -
    a finding marked "incorrect"/"already_known"/"not_actionable", or with
    consent withheld, contributes nothing, per the acceptance criteria that
    feedback data records consent and that unnecessary personal data is
    excluded from evaluation/training datasets. `repository_ref` and
    `diff_text` are pseudonymized/redacted (`app.evaluation.redaction`)
    before being written - the source repository's real identity and any
    secret-shaped token never enter this table.

    Each item's `expected_findings` covers only the single confirmed finding,
    not the whole diff's ground truth (real diffs aren't guaranteed
    single-issue like the fixed benchmark cases are) - suitable for tracking
    recall regressions on real confirmed issues across prompt/model changes.
    Precision should still be measured against the fixed benchmark
    (`app.evaluation.benchmark`), not this dataset.
    """
    next_version = (db.query(func.max(EvalDatasetVersion.version)).scalar() or 0) + 1

    rows = (
        db.query(FindingFeedback, AIFinding, DiffSnapshot, Repository)
        .join(AIFinding, FindingFeedback.ai_finding_id == AIFinding.id)
        .join(AIReview, AIFinding.ai_review_id == AIReview.id)
        .join(DiffSnapshot, AIReview.diff_snapshot_id == DiffSnapshot.id)
        .join(Repository, AIFinding.repository_id == Repository.id)
        .filter(FindingFeedback.consent.is_(True), FindingFeedback.reaction == "useful")
        .all()
    )

    dataset_version = EvalDatasetVersion(
        version=next_version,
        item_count=0,
        notes=notes,
        actor_user_id=actor_user_id,
        actor_login=actor_login,
    )
    db.add(dataset_version)
    db.flush()

    item_count = 0
    seen_finding_ids: set[int] = set()
    for _feedback, finding, diff_snapshot, repository in rows:
        if finding.id in seen_finding_ids:
            continue
        seen_finding_ids.add(finding.id)

        changed_file = next(
            (
                cf
                for cf in diff_snapshot.changed_files
                if (cf.new_path or cf.old_path) == finding.file
            ),
            None,
        )
        if changed_file is None or not changed_file.patch:
            continue

        item = EvalDatasetItem(
            dataset_version_id=dataset_version.id,
            category=finding.category,
            repository_ref=pseudonymize_repository_ref(repository.full_name),
            diff_text=redact_text(changed_file.patch),
            expected_findings=[
                {
                    "category": finding.category,
                    "severity": finding.severity,
                    "line": finding.start_line,
                }
            ],
            source_ai_finding_id=finding.id,
        )
        db.add(item)
        item_count += 1

    dataset_version.item_count = item_count
    db.commit()
    db.refresh(dataset_version)
    return dataset_version


def list_dataset_versions(db: Session) -> list[EvalDatasetVersion]:
    return db.query(EvalDatasetVersion).order_by(EvalDatasetVersion.version.desc()).all()
