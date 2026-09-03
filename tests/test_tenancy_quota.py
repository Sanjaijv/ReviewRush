from unittest.mock import MagicMock, patch

from app.ai.service import _quota_exceeded
from app.config import Settings
from app.models import Organization


class _FakeInstallation:
    github_installation_id = 1

    def __init__(self) -> None:
        self.repositories = [_FakeRepository(installation=self)]


class _FakeRepository:
    def __init__(self, installation: "_FakeInstallation | None" = None) -> None:
        self.id = 1
        self.owner = "acme"
        self.name = "widgets"
        self.full_name = "acme/widgets"
        self.installation = installation or _FakeInstallation()


def _org(**overrides) -> Organization:
    defaults = dict(id=1, installation_id=1, slug="acme", name="acme", plan="free")
    defaults.update(overrides)
    org = Organization(**defaults)
    org.installation = _FakeInstallation()
    return org


def test_organization_plan_limit_triggers_organization_scope() -> None:
    db = MagicMock()
    # repository/installation counts under limit, organization count over.
    db.query.return_value.filter.return_value.count.side_effect = [0, 0, 999]
    settings = Settings(quota_enabled=True)

    with (
        patch("app.ai.service.get_settings", return_value=settings),
        patch(
            "app.ai.service.get_or_create_organization",
            return_value=_org(plan="free", max_ai_reviews_per_day=None),
        ),
    ):
        result = _quota_exceeded(db, _FakeRepository())

    assert result == "organization"


def test_enterprise_plan_has_no_organization_limit() -> None:
    db = MagicMock()
    db.query.return_value.filter.return_value.count.side_effect = [0, 0, 999999]
    settings = Settings(quota_enabled=True)

    with (
        patch("app.ai.service.get_settings", return_value=settings),
        patch(
            "app.ai.service.get_or_create_organization",
            return_value=_org(plan="enterprise", max_ai_reviews_per_day=None),
        ),
    ):
        result = _quota_exceeded(db, _FakeRepository())

    assert result is None


def test_organization_override_beats_plan_default() -> None:
    db = MagicMock()
    db.query.return_value.filter.return_value.count.side_effect = [0, 0, 10]
    settings = Settings(quota_enabled=True)

    with (
        patch("app.ai.service.get_settings", return_value=settings),
        patch(
            "app.ai.service.get_or_create_organization",
            return_value=_org(plan="free", max_ai_reviews_per_day=5),
        ),
    ):
        result = _quota_exceeded(db, _FakeRepository())

    assert result == "organization"


def test_quota_exceeded_never_touches_required_check_settings() -> None:
    """Phase 17 acceptance criterion: billing/plan limits can only ever
    short-circuit the AI model call, never the deterministic required
    checks that gate merge eligibility."""
    settings = Settings(
        quota_enabled=True,
        analysis_semgrep_required=True,
        analysis_gitleaks_required=True,
    )
    db = MagicMock()
    db.query.return_value.filter.return_value.count.side_effect = [0, 0, 999]

    with (
        patch("app.ai.service.get_settings", return_value=settings),
        patch(
            "app.ai.service.get_or_create_organization",
            return_value=_org(plan="free", max_ai_reviews_per_day=None),
        ),
    ):
        _quota_exceeded(db, _FakeRepository())

    assert settings.analysis_semgrep_required is True
    assert settings.analysis_gitleaks_required is True
