from unittest.mock import MagicMock

import pytest

from app.feedback.service import (
    FeedbackActor,
    FindingNotFound,
    record_escaped_defect,
    submit_finding_feedback,
)
from app.models import AIFinding, EscapedDefect, FindingFeedback, Repository


def _repository() -> Repository:
    return Repository(id=1, installation_id=1, github_repo_id=1, owner="acme", name="w")


def _finding(repository_id: int = 1) -> AIFinding:
    return AIFinding(id=9, ai_review_id=1, repository_id=repository_id, file="a.py")


def _added(db: MagicMock, cls: type) -> object:
    matches = [c.args[0] for c in db.add.call_args_list if isinstance(c.args[0], cls)]
    assert matches, f"no {cls.__name__} was added"
    return matches[-1]


def test_submit_feedback_creates_row_when_none_exists() -> None:
    db = MagicMock()
    db.get.return_value = _finding()
    db.query.return_value.filter_by.return_value.one_or_none.return_value = None

    actor = FeedbackActor(user_id=1, login="octocat")
    submit_finding_feedback(
        db, _repository(), 9, actor, reaction="useful", consent=True, implemented=True
    )

    row = _added(db, FindingFeedback)
    assert row.ai_finding_id == 9
    assert row.reaction == "useful"
    assert row.consent is True
    assert row.implemented is True
    assert row.actor_login == "octocat"
    db.commit.assert_called()


def test_submit_feedback_upserts_existing_row_for_same_actor() -> None:
    db = MagicMock()
    db.get.return_value = _finding()
    existing = FindingFeedback(
        id=5, repository_id=1, ai_finding_id=9, reaction="useful", consent=True,
        retention_days=365, actor_user_id=1, actor_login="octocat",
    )
    db.query.return_value.filter_by.return_value.one_or_none.return_value = existing

    actor = FeedbackActor(user_id=1, login="octocat")
    result = submit_finding_feedback(
        db, _repository(), 9, actor, reaction="incorrect", consent=False
    )

    assert result is existing
    assert existing.reaction == "incorrect"
    assert existing.consent is False
    # no new FindingFeedback row should have been added for an upsert
    assert not any(isinstance(c.args[0], FindingFeedback) for c in db.add.call_args_list)


def test_submit_feedback_rejects_invalid_reaction() -> None:
    db = MagicMock()
    with pytest.raises(ValueError):
        submit_finding_feedback(
            db, _repository(), 9, FeedbackActor(user_id=1, login="octocat"),
            reaction="not_real", consent=True,
        )
    db.get.assert_not_called()


def test_submit_feedback_rejects_finding_from_other_repository() -> None:
    db = MagicMock()
    db.get.return_value = _finding(repository_id=2)

    with pytest.raises(FindingNotFound):
        submit_finding_feedback(
            db, _repository(), 9, FeedbackActor(user_id=1, login="octocat"),
            reaction="useful", consent=True,
        )


def test_record_escaped_defect_persists_row() -> None:
    db = MagicMock()
    actor = FeedbackActor(user_id=1, login="octocat")

    record_escaped_defect(
        db, _repository(), actor,
        description="null pointer in prod after merge",
        evidence_url="https://github.com/acme/w/commit/abc123",
    )

    row = _added(db, EscapedDefect)
    assert row.repository_id == 1
    assert row.description == "null pointer in prod after merge"
    assert row.evidence_url == "https://github.com/acme/w/commit/abc123"
    db.commit.assert_called()


def test_record_escaped_defect_rejects_finding_from_other_repository() -> None:
    db = MagicMock()
    db.get.return_value = _finding(repository_id=2)
    actor = FeedbackActor(user_id=1, login="octocat")

    with pytest.raises(FindingNotFound):
        record_escaped_defect(
            db, _repository(), actor, description="bug", ai_finding_id=9
        )
