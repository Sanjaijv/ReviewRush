from pydantic import BaseModel, Field


class FixSuggestion(BaseModel):
    """The model's proposed fix for exactly one AIFinding.

    Deliberately narrow: rather than a general patch/diff (which would need
    real patch-application logic this codebase doesn't have), the model only
    ever replaces the finding's own `start_line`..`end_line` range in its one
    file - both fields already exist and are already diff-validated on
    AIFinding, so no new "which lines are safe to touch" logic is needed.

    `applicable=False` is a legitimate, expected answer: not every finding
    has a safe, self-contained, line-range-scoped fix (e.g. one that truly
    needs a wider refactor) - the model is instructed to say so rather than
    force a fix, and the caller must never invent one when this is False.
    """

    model_config = {"extra": "forbid"}

    applicable: bool
    replacement_lines: list[str] = Field(default_factory=list)
    explanation: str = Field(default="")
