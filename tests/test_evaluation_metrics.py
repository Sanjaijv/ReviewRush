from app.evaluation.metrics import ActualFinding, ExpectedFinding, aggregate_metrics, score_case


def test_score_case_exact_match_counts_as_true_positive_with_full_accuracy() -> None:
    expected = [ExpectedFinding(category="security", severity="high", line=3)]
    actual = [ActualFinding(category="security", severity="high", start_line=3)]

    result = score_case(
        "case-1", expected, actual, latency_ms=100, prompt_tokens=10, completion_tokens=5
    )

    assert result.true_positives == 1
    assert result.false_positives == 0
    assert result.false_negatives == 0
    assert result.severity_matches == 1
    assert result.line_matches == 1


def test_score_case_wrong_severity_and_line_still_counts_as_true_positive() -> None:
    expected = [ExpectedFinding(category="security", severity="high", line=3)]
    actual = [ActualFinding(category="security", severity="critical", start_line=10)]

    result = score_case(
        "case-1", expected, actual, latency_ms=0, prompt_tokens=0, completion_tokens=0
    )

    assert result.true_positives == 1
    assert result.severity_comparisons == 1
    assert result.severity_matches == 0
    assert result.line_comparisons == 1
    assert result.line_matches == 0


def test_score_case_less_severe_actual_does_not_match() -> None:
    expected = [ExpectedFinding(category="security", severity="high", line=3)]
    actual = [ActualFinding(category="security", severity="low", start_line=3)]

    result = score_case(
        "case-1", expected, actual, latency_ms=0, prompt_tokens=0, completion_tokens=0
    )

    assert result.true_positives == 0
    assert result.false_negatives == 1
    assert result.false_positives == 1


def test_score_case_clean_diff_with_extra_finding_is_false_positive() -> None:
    result = score_case(
        "clean-case",
        expected=[],
        actual=[ActualFinding(category="maintainability", severity="low", start_line=1)],
        latency_ms=0, prompt_tokens=0, completion_tokens=0,
    )

    assert result.true_positives == 0
    assert result.false_positives == 1
    assert result.false_negatives == 0


def test_score_case_clean_diff_with_no_findings_is_perfect() -> None:
    result = score_case(
        "clean-case", expected=[], actual=[], latency_ms=0, prompt_tokens=0, completion_tokens=0
    )
    assert result.true_positives == 0
    assert result.false_positives == 0
    assert result.false_negatives == 0


def test_aggregate_metrics_computes_precision_recall_and_rates() -> None:
    results = [
        score_case(
            "tp", [ExpectedFinding(category="security", severity="high", line=1)],
            [ActualFinding(category="security", severity="high", start_line=1)],
            latency_ms=100, prompt_tokens=10, completion_tokens=5,
        ),
        score_case(
            "fn", [ExpectedFinding(category="security", severity="high", line=1)],
            [], latency_ms=200, prompt_tokens=20, completion_tokens=10,
        ),
        score_case(
            "fp", [], [ActualFinding(category="maintainability", severity="low", start_line=2)],
            latency_ms=300, prompt_tokens=30, completion_tokens=15,
        ),
    ]

    metrics = aggregate_metrics(results)

    assert metrics["case_count"] == 3
    assert metrics["true_positives"] == 1
    assert metrics["false_positives"] == 1
    assert metrics["false_negatives"] == 1
    assert metrics["precision"] == 0.5
    assert metrics["recall"] == 0.5
    assert metrics["avg_latency_ms"] == 200
    assert metrics["total_prompt_tokens"] == 60


def test_aggregate_metrics_handles_no_expected_or_actual_findings() -> None:
    results = [score_case("clean", [], [], latency_ms=0, prompt_tokens=0, completion_tokens=0)]
    metrics = aggregate_metrics(results)
    assert metrics["precision"] is None
    assert metrics["recall"] is None
    assert metrics["false_positive_rate"] == 0.0


def test_aggregate_metrics_tracks_prompt_injection_resistance() -> None:
    results = [
        score_case(
            "injected-resisted", [], [], latency_ms=0, prompt_tokens=0, completion_tokens=0,
            injection_resisted=True,
        ),
        score_case(
            "injected-failed", [], [], latency_ms=0, prompt_tokens=0, completion_tokens=0,
            injection_resisted=False,
        ),
        score_case("unrelated", [], [], latency_ms=0, prompt_tokens=0, completion_tokens=0),
    ]

    metrics = aggregate_metrics(results)
    assert metrics["prompt_injection_resistance_rate"] == 0.5
