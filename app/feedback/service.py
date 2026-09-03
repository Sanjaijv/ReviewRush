from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.config import get_settings
from app.dashboard.audit import record_audit_event
from app.models import AIFinding, EscapedDefect, FindingFeedback, Repository

_VALID_REACTIONS = frozenset({"useful", "incorrect", "already_known", "not_actionable"})


class FindingNotFound(Exception):
    pass


@dataclass(frozen=True)
class FeedbackActor:
    """Whoever is submitting feedback or recording an escaped defect -
    always the authenticated dashboard user (Phase 12), never inferred from
    unauthenticated input.
    """

    user_id: int
    login: str


def submit_finding_feedback(
    db: Session,
    repository: Repository,
    finding_id: int,
    actor: FeedbackActor,
    *,
    reaction: str,
    consent: bool,
    implemented: bool | None = None,
    notes: str | None = None,
) -> FindingFeedback:
    """Record (or update) one developer's reaction to one AIFinding.

    `consent` must be given explicitly by the caller every time - it is
    never defaulted to True. A finding not belonging to this repository
    raises FindingNotFound so a caller can't attach feedback to another
    tenant's finding by guessing an id.
    """
    if reaction not in _VALID_REACTIONS:
        raise ValueError(f"invalid reaction: {reaction!r}")

    finding: Any = db.get(AIFinding, finding_id)
    if finding is None or finding.repository_id != repository.id:
        raise FindingNotFound(finding_id)

    settings = get_settings()
    existing = (
        db.query(FindingFeedback)
        .filter_by(ai_finding_id=finding_id, actor_user_id=actor.user_id)
        .one_or_none()
    )

    if existing is not None:
        existing.reaction = reaction
        existing.consent = consent
        existing.implemented = implemented
        existing.notes = notes
        row = existing
    else:
        row = FindingFeedback(
            repository_id=repository.id,
            ai_finding_id=finding_id,
            reaction=reaction,
            consent=consent,
            implemented=implemented,
            notes=notes,
            provenance="dashboard",
            retention_days=settings.feedback_default_retention_days,
            actor_user_id=actor.user_id,
            actor_login=actor.login,
        )
        db.add(row)

    db.flush()
    record_audit_event(
        db,
        action="finding_feedback.submitted",
        target_type="ai_finding",
        target_id=str(finding_id),
        repository_id=repository.id,
        actor_type="user",
        actor_user_id=actor.user_id,
        actor_login=actor.login,
        metadata={"reaction": reaction, "consent": consent},
    )
    db.commit()
    db.refresh(row)
    return row


def list_finding_feedback(
    db: Session, repository: Repository, finding_id: int
) -> list[FindingFeedback]:
    return (
        db.query(FindingFeedback)
        .filter_by(repository_id=repository.id, ai_finding_id=finding_id)
        .order_by(FindingFeedback.created_at.desc())
        .all()
    )


def record_escaped_defect(
    db: Session,
    repository: Repository,
    actor: FeedbackActor,
    *,
    description: str,
    pull_request_id: int | None = None,
    diff_snapshot_id: int | None = None,
    ai_finding_id: int | None = None,
    evidence_url: str | None = None,
    detected_at: datetime | None = None,
) -> EscapedDefect:
    """Record one defect known (via concrete evidence) to have escaped
    review. Never inferred automatically - always a human-asserted fact
    with an optional evidence_url pointing at the proof (revert, incident,
    follow-up bug report).
    """
    if ai_finding_id is not None:
        finding: Any = db.get(AIFinding, ai_finding_id)
        if finding is None or finding.repository_id != repository.id:
            raise FindingNotFound(ai_finding_id)

    row = EscapedDefect(
        repository_id=repository.id,
        pull_request_id=pull_request_id,
        diff_snapshot_id=diff_snapshot_id,
        ai_finding_id=ai_finding_id,
        description=description,
        evidence_url=evidence_url,
        detected_at=detected_at or datetime.now(UTC),
        actor_user_id=actor.user_id,
        actor_login=actor.login,
    )
    db.add(row)
    db.flush()
    record_audit_event(
        db,
        action="escaped_defect.recorded",
        target_type="escaped_defect",
        target_id=str(row.id),
        repository_id=repository.id,
        actor_type="user",
        actor_user_id=actor.user_id,
        actor_login=actor.login,
        metadata={"ai_finding_id": ai_finding_id},
    )
    db.commit()
    db.refresh(row)
    return row


def list_escaped_defects(db: Session, repository: Repository) -> list[EscapedDefect]:
    return (
        db.query(EscapedDefect)
        .filter_by(repository_id=repository.id)
        .order_by(EscapedDefect.created_at.desc())
        .all()
    )
