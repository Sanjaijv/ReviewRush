from typing import Any

from pydantic import ValidationError

from app.autofix.schema import FixSuggestion


def validate_fix_suggestion(raw: dict[str, Any] | None) -> tuple[FixSuggestion | None, list[str]]:
    """Validate raw model output against the FixSuggestion contract.

    Fails closed: any schema violation, or `applicable=True` with an empty
    `replacement_lines`, invalidates the whole output rather than being
    silently coerced into something the caller might apply. A caller must
    treat `(None, errors)` as "no fix" and `(_, []) with applicable=False`
    the same way - both mean nothing gets written to the file.
    """
    if raw is None:
        return None, ["model produced no parseable output"]

    try:
        suggestion = FixSuggestion.model_validate(raw)
    except ValidationError as exc:
        return None, [f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()]

    if suggestion.applicable and not suggestion.replacement_lines:
        return None, ["applicable=true but replacement_lines is empty"]

    return suggestion, []
