from unittest.mock import MagicMock, patch

from app.ai.model import ModelResponse
from app.ai.service import run_ai_review_for_snapshot
from app.config import Settings
from app.models import AIReview, ChangedFile, DiffSnapshot

_VALID_PATCH = "@@ -1,3 +1,4 @@\n context1\n-removed1\n+added1\n+added2\n context2"

_VALID_CONTENT = {
    "summary": "Looks fine.",
    "risk": "low",
    "confidence": 0.91,
    "decision": "approve",
    "issues": [
        {
            "file": "src/app.py",
            "start_line": 2,
            "end_line": 2,
            "severity": "medium",
            "category": "maintainability",
            "title": "issue",
            "evidence": "evidence text",
            "recommendation": "recommend",
        }
    ],
}


class _FakeInstallation:
    id = 1
    github_installation_id = 1
    account_login = "acme"
    repositories: list = []


class _FakeRepository:
    def __init__(self) -> None:
        self.id = 1
        self.owner = "acme"
        self.name = "widgets"
        self.full_name = "acme/widgets"
        self.installation = _FakeInstallation()


class _FakeModel:
    def __init__(self, responses: list[ModelResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[dict] = []

    def generate(self, *, system, messages, response_schema=None):
        self.calls.append({"system": system, "messages": messages})
        return self._responses.pop(0)


def _response(content, *, error=None, raw_text="") -> ModelResponse:
    return ModelResponse(
        content=content, raw_text=raw_text or str(content), prompt_tokens=10,
        completion_tokens=5, latency_ms=1, error=error,
    )


def _diff_snapshot() -> DiffSnapshot:
    snapshot = DiffSnapshot(
        id=1, repository_id=1, head_sha="sha1", base_sha="mainsha", commits=[]
    )
    snapshot.changed_files = [
        ChangedFile(
            new_path="src/app.py", old_path="src/app.py", status="modified", patch=_VALID_PATCH
        )
    ]
    return snapshot


def _db_with_no_existing_review() -> MagicMock:
    db = MagicMock()
    db.query.return_value.filter_by.return_value.one_or_none.return_value = None
    db.query.return_value.filter_by.return_value.all.return_value = []
    return db


def _settings(**overrides) -> Settings:
    base = dict(ai_review_enabled=True)
    base.update(overrides)
    return Settings(**base)


def _run(db, settings, model):
    with (
        patch("app.ai.service.get_settings", return_value=settings),
        patch("app.ai.service.get_installation_access_token", return_value="tok"),
        patch("app.ai.service.GitHubClient") as github_client_cls,
        patch("app.ai.service.build_review_model", return_value=model),
    ):
        instance = MagicMock()
        instance.get_file_contents.return_value = None
        instance.__enter__.return_value = instance
        github_client_cls.return_value = instance
        return run_ai_review_for_snapshot(db, _FakeRepository(), _diff_snapshot())


def test_disabled_flag_skips_without_calling_model() -> None:
    db = _db_with_no_existing_review()
    model = _FakeModel([])
    result = _run(db, _settings(ai_review_enabled=False), model)

    assert result is None
    assert model.calls == []
    db.add.assert_not_called()


def test_existing_review_is_reused_without_calling_model() -> None:
    db = MagicMock()
    existing = AIReview(id=5, repository_id=1, diff_snapshot_id=1, status="completed")
    db.query.return_value.filter_by.return_value.one_or_none.return_value = existing
    model = _FakeModel([])

    result = _run(db, _settings(), model)

    assert result is existing
    assert model.calls == []
    db.add.assert_not_called()


def test_valid_first_response_is_persisted_as_completed() -> None:
    db = _db_with_no_existing_review()
    model = _FakeModel([_response(_VALID_CONTENT)])

    _run(db, _settings(), model)

    assert len(model.calls) == 1
    # db.add is also called once to provision the Organization the
    # repository's installation belongs to (Phase 17) - the AIReview is the
    # most recent add, which is what call_args (the last call) captures.
    persisted: AIReview = db.add.call_args[0][0]
    assert persisted.status == "completed"
    assert persisted.decision == "approve"
    assert len(persisted.findings) == 1
    assert persisted.attempt_count == 1


def test_invalid_then_valid_response_triggers_one_repair_retry() -> None:
    db = _db_with_no_existing_review()
    model = _FakeModel([
        _response({"summary": "bad", "risk": "not-a-risk", "confidence": 0.5,
                    "decision": "approve", "issues": []}),
        _response(_VALID_CONTENT),
    ])

    _run(db, _settings(), model)

    assert len(model.calls) == 2
    # the repair turn must include the original prompt + prior reply + correction
    repair_messages = model.calls[1]["messages"]
    assert repair_messages[0]["role"] == "user"
    assert repair_messages[1]["role"] == "assistant"
    assert repair_messages[2]["role"] == "user"

    persisted: AIReview = db.add.call_args[0][0]
    assert persisted.status == "completed"
    assert persisted.attempt_count == 2


def test_both_attempts_invalid_persists_invalid_output_with_no_findings() -> None:
    db = _db_with_no_existing_review()
    bad = {"summary": "bad", "risk": "not-a-risk", "confidence": 0.5,
           "decision": "approve", "issues": []}
    model = _FakeModel([_response(bad), _response(bad)])

    _run(db, _settings(), model)

    assert len(model.calls) == 2
    persisted: AIReview = db.add.call_args[0][0]
    assert persisted.status == "invalid_output"
    assert persisted.decision is None
    assert persisted.findings == []


def test_model_error_both_attempts_persists_error_status() -> None:
    db = _db_with_no_existing_review()
    model = _FakeModel([
        _response(None, error="ollama request timed out"),
        _response(None, error="ollama request timed out"),
    ])

    _run(db, _settings(), model)

    persisted: AIReview = db.add.call_args[0][0]
    assert persisted.status == "error"
    assert persisted.decision is None


def test_unknown_provider_persists_error_without_calling_model() -> None:
    db = _db_with_no_existing_review()

    _run(db, _settings(), None)

    persisted: AIReview = db.add.call_args[0][0]
    assert persisted.status == "error"
