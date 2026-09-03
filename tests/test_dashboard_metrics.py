from unittest.mock import MagicMock

from app.dashboard.metrics import compute_repository_metrics


def _chain(*, scalar=None, all_rows=None) -> MagicMock:
    """One db.query(...) call's chain: .filter(...).group_by(...).scalar()/.all()"""
    q = MagicMock()
    q.filter.return_value = q
    q.group_by.return_value = q
    q.scalar.return_value = scalar
    q.all.return_value = all_rows or []
    return q


def test_aggregates_into_expected_shape() -> None:
    db = MagicMock()
    db.query.side_effect = [
        _chain(scalar=12),  # total_reviews
        _chain(scalar=4200.0),  # avg_review_time_ms
        _chain(all_rows=[("high", 2), ("low", 5)]),  # findings_by_severity
        _chain(all_rows=[("APPROVE", 8), ("HUMAN_REVIEW", 3), ("BLOCK", 1)]),  # policy decisions
        _chain(all_rows=[("merged", 6), ("not_eligible", 4)]),  # merge attempts
        _chain(all_rows=[("ollama", "qwen2.5-coder:7b", 12, 50000, 8000)]),  # model usage
        _chain(all_rows=[("useful", 6), ("incorrect", 2)]),  # feedback by reaction
    ]

    result = compute_repository_metrics(db, repository_id=1)

    assert result["total_reviews"] == 12
    assert result["avg_review_time_ms"] == 4200.0
    assert result["findings_by_severity"] == {"high": 2, "low": 5}
    assert result["blocked_merges"] == 4  # HUMAN_REVIEW(3) + BLOCK(1)
    assert result["merge_attempts_by_outcome"] == {"merged": 6, "not_eligible": 4}
    assert result["model_usage"] == [
        {
            "provider": "ollama",
            "model": "qwen2.5-coder:7b",
            "review_count": 12,
            "prompt_tokens": 50000,
            "completion_tokens": 8000,
        }
    ]
    assert result["feedback_by_reaction"] == {"useful": 6, "incorrect": 2}
    assert result["false_positive_rate"] == 0.25


def test_empty_repository_reports_zeros_not_errors() -> None:
    db = MagicMock()
    db.query.side_effect = [
        _chain(scalar=0),
        _chain(scalar=None),
        _chain(all_rows=[]),
        _chain(all_rows=[]),
        _chain(all_rows=[]),
        _chain(all_rows=[]),
        _chain(all_rows=[]),
    ]

    result = compute_repository_metrics(db, repository_id=1)

    assert result["total_reviews"] == 0
    assert result["avg_review_time_ms"] is None
    assert result["blocked_merges"] == 0
    assert result["false_positive_rate"] is None
