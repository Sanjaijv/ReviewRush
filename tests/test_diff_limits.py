from app.diffs.limits import DiffLimits, evaluate_limits

_LIMITS = DiffLimits(
    max_files=10,
    max_file_patch_bytes=1000,
    max_total_changed_lines=100,
    max_total_prompt_bytes=5000,
)


def test_within_all_limits_is_not_oversized() -> None:
    result = evaluate_limits(
        _LIMITS, file_count=5, total_changed_lines=50, total_patch_bytes=1000
    )
    assert result.oversized is False
    assert result.reasons == []


def test_exceeding_file_count_is_oversized() -> None:
    result = evaluate_limits(
        _LIMITS, file_count=11, total_changed_lines=50, total_patch_bytes=1000
    )
    assert result.oversized is True
    assert "file_count" in result.reasons[0]


def test_exceeding_total_changed_lines_is_oversized() -> None:
    result = evaluate_limits(
        _LIMITS, file_count=5, total_changed_lines=101, total_patch_bytes=1000
    )
    assert result.oversized is True
    assert any("total_changed_lines" in reason for reason in result.reasons)


def test_exceeding_total_prompt_bytes_is_oversized() -> None:
    result = evaluate_limits(
        _LIMITS, file_count=5, total_changed_lines=50, total_patch_bytes=5001
    )
    assert result.oversized is True
    assert any("total_patch_bytes" in reason for reason in result.reasons)


def test_multiple_violations_are_all_reported() -> None:
    result = evaluate_limits(
        _LIMITS, file_count=20, total_changed_lines=200, total_patch_bytes=6000
    )
    assert result.oversized is True
    assert len(result.reasons) == 3
