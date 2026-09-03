from typing import Literal

from pydantic import BaseModel, Field, model_validator

Severity = Literal["low", "medium", "high", "critical"]
Category = Literal[
    "correctness",
    "security",
    "reliability",
    "performance",
    "maintainability",
    "compatibility",
    "error_handling",
    "concurrency",
    "missing_tests",
]
RiskLevel = Literal["low", "medium", "high", "critical"]

# No "merge" value exists here on purpose: the AI can only advise, never
# request a merge - that decision belongs to the policy engine (Phase 7).
Decision = Literal["approve", "comment", "request_changes"]

_SEVERITY_RANK: dict[str, int] = {"critical": 0, "high": 1, "medium": 2, "low": 3}


class AIReviewIssue(BaseModel):
    """One finding, matching the Phase 6 output contract's `issues[]` entries.

    `evidence` is required and non-empty so a finding can never be persisted
    without the model stating what in the diff supports it.
    """

    model_config = {"extra": "forbid"}

    file: str = Field(min_length=1)
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    severity: Severity
    category: Category
    title: str = Field(min_length=1, max_length=200)
    evidence: str = Field(min_length=1)
    recommendation: str = Field(default="")
    # Ids of items from the "Repository context" prompt section (Phase 10)
    # this finding relied on, if any. Empty when the finding came from the
    # diff alone or no repository context was available for this review.
    context_refs: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _end_line_not_before_start(self) -> "AIReviewIssue":
        if self.end_line < self.start_line:
            raise ValueError("end_line must be >= start_line")
        return self

    @property
    def severity_rank(self) -> int:
        return _SEVERITY_RANK.get(self.severity, len(_SEVERITY_RANK))


class AIReviewOutput(BaseModel):
    """The required Phase 6 output contract. Validated with
    `model_validate` against raw model output before anything is trusted.
    """

    model_config = {"extra": "forbid"}

    summary: str = Field(min_length=1)
    risk: RiskLevel
    confidence: float = Field(ge=0.0, le=1.0)
    decision: Decision
    issues: list[AIReviewIssue] = Field(default_factory=list)
