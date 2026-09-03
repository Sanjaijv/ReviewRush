from app.checks.fingerprint import finding_fingerprint, meets_inline_threshold, severity_rank
from app.models import AIFinding


def _finding(**overrides) -> AIFinding:
    defaults = dict(
        file="src/app.py",
        start_line=10,
        end_line=12,
        severity="high",
        category="security",
        title="Missing ownership check",
        evidence="...",
    )
    defaults.update(overrides)
    return AIFinding(**defaults)


def test_fingerprint_is_stable_for_identical_content() -> None:
    a = _finding()
    b = _finding()
    assert finding_fingerprint(a) == finding_fingerprint(b)


def test_fingerprint_ignores_row_identity() -> None:
    a = _finding()
    b = _finding()
    a.id = 1
    b.id = 2
    assert finding_fingerprint(a) == finding_fingerprint(b)


def test_fingerprint_changes_when_content_changes() -> None:
    a = _finding()
    b = _finding(title="A different issue")
    assert finding_fingerprint(a) != finding_fingerprint(b)


def test_severity_rank_orders_critical_first() -> None:
    ranks = [severity_rank(s) for s in ("critical", "high", "medium", "low")]
    assert ranks == sorted(ranks)
    assert len(set(ranks)) == 4


def test_severity_rank_unknown_fails_closed_to_worst() -> None:
    assert severity_rank("unknown") == severity_rank("critical")


def test_meets_inline_threshold() -> None:
    assert meets_inline_threshold("critical", "medium") is True
    assert meets_inline_threshold("medium", "medium") is True
    assert meets_inline_threshold("low", "medium") is False
