from dataclasses import replace

from app.merge.eligibility import (
    MergeEligibilityInput,
    RequiredCheckResult,
    evaluate_merge_eligibility,
)


def _baseline() -> MergeEligibilityInput:
    """All-passing input: should be eligible."""
    return MergeEligibilityInput(
        auto_merge_enabled=True,
        policy_decision="APPROVE",
        policy_risk="LOW",
        protected_paths_matched=False,
        reviewed_head_sha="sha1",
        pr_head_sha="sha1",
        pr_base_branch="main",
        expected_base_branch="main",
        pr_state="open",
        pr_merged=False,
        pr_draft=False,
        mergeable=True,
        mergeable_state="clean",
        check_runs=[
            RequiredCheckResult(name="ReviewRush", status="completed", conclusion="success")
        ],
        changes_requested_reviews=0,
    )


def test_baseline_is_eligible() -> None:
    result = evaluate_merge_eligibility(_baseline())
    assert result.eligible
    assert result.reasons == []


def test_auto_merge_disabled_blocks() -> None:
    result = evaluate_merge_eligibility(replace(_baseline(), auto_merge_enabled=False))
    assert not result.eligible
    assert any("disabled" in r for r in result.reasons)


def test_already_merged_blocks() -> None:
    result = evaluate_merge_eligibility(replace(_baseline(), pr_merged=True))
    assert not result.eligible
    assert any("already merged" in r for r in result.reasons)


def test_closed_pr_blocks() -> None:
    result = evaluate_merge_eligibility(replace(_baseline(), pr_state="closed"))
    assert not result.eligible


def test_draft_pr_blocks() -> None:
    result = evaluate_merge_eligibility(replace(_baseline(), pr_draft=True))
    assert not result.eligible


def test_stale_head_sha_blocks() -> None:
    result = evaluate_merge_eligibility(replace(_baseline(), pr_head_sha="sha2"))
    assert not result.eligible
    assert any("advanced past the reviewed commit" in r for r in result.reasons)


def test_base_branch_changed_blocks() -> None:
    result = evaluate_merge_eligibility(replace(_baseline(), pr_base_branch="develop"))
    assert not result.eligible


def test_non_approve_decision_blocks() -> None:
    result = evaluate_merge_eligibility(replace(_baseline(), policy_decision="HUMAN_REVIEW"))
    assert not result.eligible


def test_non_low_risk_blocks_even_if_approved() -> None:
    result = evaluate_merge_eligibility(replace(_baseline(), policy_risk="MEDIUM"))
    assert not result.eligible
    assert any("not LOW" in r for r in result.reasons)


def test_protected_path_match_blocks() -> None:
    result = evaluate_merge_eligibility(replace(_baseline(), protected_paths_matched=True))
    assert not result.eligible


def test_not_mergeable_blocks() -> None:
    result = evaluate_merge_eligibility(replace(_baseline(), mergeable=False))
    assert not result.eligible


def test_unknown_mergeable_state_blocks() -> None:
    result = evaluate_merge_eligibility(replace(_baseline(), mergeable_state="unknown"))
    assert not result.eligible


def test_incomplete_check_run_blocks() -> None:
    inp = replace(
        _baseline(),
        check_runs=[RequiredCheckResult(name="ci", status="in_progress", conclusion=None)],
    )
    result = evaluate_merge_eligibility(inp)
    assert not result.eligible
    assert any("has not completed" in r for r in result.reasons)


def test_failed_check_run_blocks() -> None:
    inp = replace(
        _baseline(),
        check_runs=[RequiredCheckResult(name="ci", status="completed", conclusion="failure")],
    )
    result = evaluate_merge_eligibility(inp)
    assert not result.eligible
    assert any("did not pass" in r for r in result.reasons)


def test_no_check_runs_blocks() -> None:
    result = evaluate_merge_eligibility(replace(_baseline(), check_runs=[]))
    assert not result.eligible
    assert any("no check runs" in r for r in result.reasons)


def test_changes_requested_review_blocks() -> None:
    result = evaluate_merge_eligibility(replace(_baseline(), changes_requested_reviews=1))
    assert not result.eligible
    assert any("requested changes" in r for r in result.reasons)


def test_multiple_failures_are_all_reported() -> None:
    inp = replace(_baseline(), auto_merge_enabled=False, policy_risk="HIGH", mergeable=False)
    result = evaluate_merge_eligibility(inp)
    assert not result.eligible
    assert len(result.reasons) >= 3
