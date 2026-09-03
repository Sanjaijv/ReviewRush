from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models import Organization


@dataclass(frozen=True)
class PlanLimits:
    """Default usage ceilings for one billing plan tier.

    `None` means unlimited. These are code-level defaults, not billing
    system state - there is no payment processor integrated in this release
    (Phase 17 scope was deliberately limited to internal metering). An
    `Organization` row can override either field individually
    (`max_ai_reviews_per_day` / `max_repositories`); a null override defers
    to the plan default here.
    """

    max_ai_reviews_per_day: int | None
    max_repositories: int | None


PLAN_DEFAULTS: dict[str, PlanLimits] = {
    "free": PlanLimits(max_ai_reviews_per_day=50, max_repositories=3),
    "pro": PlanLimits(max_ai_reviews_per_day=500, max_repositories=25),
    "enterprise": PlanLimits(max_ai_reviews_per_day=None, max_repositories=None),
}

DEFAULT_PLAN = "free"


def resolve_limits(organization: "Organization") -> PlanLimits:
    defaults = PLAN_DEFAULTS.get(organization.plan, PLAN_DEFAULTS[DEFAULT_PLAN])
    return PlanLimits(
        max_ai_reviews_per_day=(
            organization.max_ai_reviews_per_day
            if organization.max_ai_reviews_per_day is not None
            else defaults.max_ai_reviews_per_day
        ),
        max_repositories=(
            organization.max_repositories
            if organization.max_repositories is not None
            else defaults.max_repositories
        ),
    )
