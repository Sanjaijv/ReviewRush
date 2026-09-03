from app.models import ChangedFile
from app.reviewers.definitions import REVIEWER_DEFINITIONS, ReviewerDefinition


def select_reviewers(changed_files: list[ChangedFile]) -> list[ReviewerDefinition]:
    """Return the specialized reviewers whose selection predicate matches
    this diff's changed files, in a fixed, deterministic order.

    Pure and side-effect-free: no model call, no DB access, so which
    reviewers would run for a given diff can be tested and audited without
    incurring any cost.
    """
    return [d for d in REVIEWER_DEFINITIONS if d.selector(changed_files)]
