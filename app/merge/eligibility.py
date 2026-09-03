from dataclasses import dataclass, field

_PASSING_CONCLUSIONS = {"success", "neutral", "skipped"}


@dataclass(frozen=True)
class RequiredCheckResult:
    """One observed check-run, re-fetched live from GitHub for the reviewed
    head_sha - never taken from our own stored ToolRun rows, which only
    know about the checks *we* ran, not every check-run GitHub is tracking.
    """

    name: str
    status: str  # "queued" / "in_progress" / "completed"
    conclusion: str | None


@dataclass(frozen=True)
class MergeEligibilityInput:
    """Everything needed to decide auto-merge eligibility, already re-fetched
    live from GitHub by the caller (`app.merge.service`) so this function
    stays pure and depends on no state that could have gone stale between
    being read and being evaluated.
    """

    auto_merge_enabled: bool

    policy_decision: str
    policy_risk: str
    protected_paths_matched: bool

    reviewed_head_sha: str
    pr_head_sha: str
    pr_base_branch: str
    expected_base_branch: str
    pr_state: str
    pr_merged: bool
    pr_draft: bool

    mergeable: bool | None
    mergeable_state: str | None

    check_runs: list[RequiredCheckResult] = field(default_factory=list)
    changes_requested_reviews: int = 0


@dataclass(frozen=True)
class MergeEligibilityResult:
    eligible: bool
    reasons: list[str]


def evaluate_merge_eligibility(inp: MergeEligibilityInput) -> MergeEligibilityResult:
    """Fail-closed: any unmet condition blocks the merge. Checks are ordered
    cheapest/most-decisive first, but every reason is still collected so the
    audit log explains everything that was wrong, not just the first thing.
    """
    reasons: list[str] = []

    if not inp.auto_merge_enabled:
        reasons.append("auto-merge is disabled (organization or repository setting)")

    if inp.pr_merged:
        reasons.append("pull request is already merged")
    if inp.pr_state != "open":
        reasons.append(f"pull request is not open (state={inp.pr_state})")
    if inp.pr_draft:
        reasons.append("pull request is a draft")

    if inp.pr_head_sha != inp.reviewed_head_sha:
        reasons.append(
            "pull request head has advanced past the reviewed commit "
            f"(reviewed={inp.reviewed_head_sha}, current={inp.pr_head_sha})"
        )
    if inp.pr_base_branch != inp.expected_base_branch:
        reasons.append(
            f"pull request base branch changed (expected={inp.expected_base_branch}, "
            f"current={inp.pr_base_branch})"
        )

    if inp.policy_decision != "APPROVE":
        reasons.append(f"policy decision is {inp.policy_decision}, not APPROVE")
    if inp.policy_risk != "LOW":
        reasons.append(f"risk is {inp.policy_risk}, not LOW")
    if inp.protected_paths_matched:
        reasons.append("a protected path requires human review")

    if inp.mergeable is not True:
        reasons.append(f"github reports the pull request is not mergeable ({inp.mergeable!r})")
    if inp.mergeable_state != "clean":
        reasons.append(f"mergeable_state is {inp.mergeable_state!r}, not 'clean'")

    if not inp.check_runs:
        reasons.append("no check runs found for this commit")
    for run in inp.check_runs:
        if run.status != "completed":
            reasons.append(f"check run '{run.name}' has not completed (status={run.status})")
        elif run.conclusion not in _PASSING_CONCLUSIONS:
            reasons.append(f"check run '{run.name}' did not pass (conclusion={run.conclusion})")

    if inp.changes_requested_reviews > 0:
        reasons.append(
            f"{inp.changes_requested_reviews} review(s) have requested changes"
        )

    return MergeEligibilityResult(eligible=not reasons, reasons=reasons)
