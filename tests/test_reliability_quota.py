from unittest.mock import MagicMock, patch

from app.ai.model import ModelResponse
from app.ai.service import _quota_exceeded, run_ai_review_for_snapshot
from app.config import Settings
from app.models import ChangedFile, DiffSnapshot


class _FakeInstallation:
    id = 1
    github_installation_id = 1
    account_login = "acme"

    def __init__(self) -> None:
        self.repositories = [_FakeRepository(installation=self)]


class _FakeRepository:
    def __init__(self, installation: _FakeInstallation | None = None) -> None:
        self.id = 1
        self.owner = "acme"
        self.name = "widgets"
        self.full_name = "acme/widgets"
        self.installation = installation or _FakeInstallation()


class _FakeModel:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def generate(self, *, system, messages, response_schema=None):
        self.calls.append({"system": system, "messages": messages})
        return ModelResponse(
            content=None, raw_text="", prompt_tokens=0, completion_tokens=0, latency_ms=0,
            error="should not be called",
        )


def _diff_snapshot() -> DiffSnapshot:
    snapshot = DiffSnapshot(id=1, repository_id=1, head_sha="sha1", base_sha="mainsha", commits=[])
    snapshot.changed_files = [
        ChangedFile(new_path="src/app.py", old_path="src/app.py", status="modified", patch="")
    ]
    return snapshot


def test_quota_exceeded_returns_none_when_disabled() -> None:
    db = MagicMock()
    settings = Settings(quota_enabled=False)

    with patch("app.ai.service.get_settings", return_value=settings):
        assert _quota_exceeded(db, _FakeRepository()) is None
    db.query.assert_not_called()


def test_quota_exceeded_flags_repository_scope_over_limit() -> None:
    db = MagicMock()
    db.query.return_value.filter.return_value.count.return_value = 999
    settings = Settings(
        quota_enabled=True,
        quota_max_ai_reviews_per_repository_per_day=5,
        quota_max_ai_reviews_per_installation_per_day=1000,
    )

    with patch("app.ai.service.get_settings", return_value=settings):
        assert _quota_exceeded(db, _FakeRepository()) == "repository"


def test_quota_exceeded_within_limits_returns_none() -> None:
    db = MagicMock()
    db.query.return_value.filter.return_value.count.return_value = 0
    # No existing Organization row - get_or_create_organization takes the
    # create path and resolves plan limits from PLAN_DEFAULTS, not from a
    # MagicMock attribute.
    db.query.return_value.filter_by.return_value.one_or_none.return_value = None
    settings = Settings(quota_enabled=True)

    with patch("app.ai.service.get_settings", return_value=settings):
        assert _quota_exceeded(db, _FakeRepository()) is None


def test_ai_review_skips_model_call_and_persists_quota_exceeded_status() -> None:
    db = MagicMock()
    db.query.return_value.filter_by.return_value.one_or_none.return_value = None
    db.query.return_value.filter.return_value.count.return_value = 999
    model = _FakeModel()

    settings = Settings(ai_review_enabled=True, quota_enabled=True)

    with (
        patch("app.ai.service.get_settings", return_value=settings),
        patch("app.ai.service.build_review_model", return_value=model),
    ):
        result = run_ai_review_for_snapshot(db, _FakeRepository(), _diff_snapshot())

    assert model.calls == []
    assert result is not None
    assert result.status == "quota_exceeded"
    assert result.decision is None  # never an implicit approval
