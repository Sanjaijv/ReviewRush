import pytest
from sqlalchemy import text

from app.autofix.service import eligible_findings
from app.config import Settings
from app.models import AIFinding, AIReview, AutoFixAttempt, DiffSnapshot, Installation, Repository
from app.repo_config import AutoFixConfig, RepoConfig


@pytest.fixture(autouse=True)
def _cleanup(db_session):
    yield
    db_session.execute(text("DELETE FROM auto_fix_attempts"))
    db_session.execute(text("DELETE FROM audit_events"))
    db_session.execute(text("DELETE FROM ai_findings"))
    db_session.execute(text("DELETE FROM ai_reviews"))
    db_session.execute(text("DELETE FROM diff_snapshots"))
    db_session.execute(text("DELETE FROM repositories"))
    db_session.execute(text("DELETE FROM organization_members"))
    db_session.execute(text("DELETE FROM organizations"))
    db_session.execute(text("DELETE FROM installations"))
    db_session.commit()


def _settings(max_fixes: int = 10) -> Settings:
    return Settings(autofix_max_fixes_per_snapshot=max_fixes)


def _review_with_findings(db_session, findings_kwargs: list[dict]) -> AIReview:
    installation = Installation(
        github_installation_id=5001, account_login="acme", account_type="Organization"
    )
    db_session.add(installation)
    db_session.commit()

    repository = Repository(
        installation_id=installation.id, github_repo_id=1, owner="acme", name="widgets",
        full_name="acme/widgets",
    )
    db_session.add(repository)
    db_session.commit()

    snapshot = DiffSnapshot(repository_id=repository.id, head_sha="sha1", base_sha="mainsha")
    db_session.add(snapshot)
    db_session.commit()

    review = AIReview(
        repository_id=repository.id, diff_snapshot_id=snapshot.id, status="completed",
        decision="comment", risk="low", confidence=0.9,
    )
    review.findings = [
        AIFinding(
            repository_id=repository.id, file="app.py", start_line=1, end_line=1, **kwargs
        )
        for kwargs in findings_kwargs
    ]
    db_session.add(review)
    db_session.commit()
    return review


def _config(enabled: bool = True, maximum_severity: str = "low") -> RepoConfig:
    return RepoConfig(auto_fix=AutoFixConfig(enabled=enabled, maximum_severity=maximum_severity))


def test_disabled_repo_config_returns_nothing(db_session) -> None:
    review = _review_with_findings(
        db_session,
        [{"severity": "low", "category": "maintainability", "title": "x", "evidence": "e"}],
    )
    result = eligible_findings(db_session, review, _config(enabled=False), _settings())
    assert result == []


def test_security_category_is_never_eligible_even_with_medium_ceiling(db_session) -> None:
    review = _review_with_findings(
        db_session,
        [{"severity": "low", "category": "security", "title": "x", "evidence": "e"}],
    )
    result = eligible_findings(db_session, review, _config(maximum_severity="medium"), _settings())
    assert result == []


def test_missing_tests_category_is_never_eligible(db_session) -> None:
    review = _review_with_findings(
        db_session,
        [{"severity": "low", "category": "missing_tests", "title": "x", "evidence": "e"}],
    )
    result = eligible_findings(db_session, review, _config(), _settings())
    assert result == []


def test_severity_above_configured_ceiling_is_excluded(db_session) -> None:
    review = _review_with_findings(
        db_session,
        [{"severity": "medium", "category": "maintainability", "title": "x", "evidence": "e"}],
    )
    # default ceiling is "low" only
    result = eligible_findings(db_session, review, _config(maximum_severity="low"), _settings())
    assert result == []

    result_medium = eligible_findings(
        db_session, review, _config(maximum_severity="medium"), _settings()
    )
    assert len(result_medium) == 1


def test_high_and_critical_are_never_eligible_regardless_of_config(db_session) -> None:
    review = _review_with_findings(
        db_session,
        [
            {"severity": "high", "category": "maintainability", "title": "x", "evidence": "e"},
            {"severity": "critical", "category": "maintainability", "title": "y", "evidence": "e"},
        ],
    )
    # AutoFixConfig itself rejects "high"/"critical" as maximum_severity, but
    # the enforcement in eligible_findings must hold regardless.
    result = eligible_findings(db_session, review, _config(maximum_severity="medium"), _settings())
    assert result == []


def test_already_attempted_finding_is_not_eligible_again(db_session) -> None:
    review = _review_with_findings(
        db_session,
        [{"severity": "low", "category": "maintainability", "title": "x", "evidence": "e"}],
    )
    finding = review.findings[0]
    db_session.add(
        AutoFixAttempt(
            repository_id=review.repository_id, diff_snapshot_id=review.diff_snapshot_id,
            ai_finding_id=finding.id, status="pr_opened",
        )
    )
    db_session.commit()

    result = eligible_findings(db_session, review, _config(), _settings())
    assert result == []


def test_eligible_findings_capped_at_max_fixes_per_snapshot(db_session) -> None:
    review = _review_with_findings(
        db_session,
        [
            {"severity": "low", "category": "maintainability", "title": f"x{i}", "evidence": "e"}
            for i in range(5)
        ],
    )
    result = eligible_findings(db_session, review, _config(), _settings(max_fixes=2))
    assert len(result) == 2
