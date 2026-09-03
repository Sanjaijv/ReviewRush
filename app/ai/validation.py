from typing import Any

from pydantic import ValidationError

from app.ai.schema import AIReviewIssue, AIReviewOutput
from app.diffs.patch import map_added_lines
from app.models import ChangedFile


def _validation_error_messages(exc: ValidationError) -> list[str]:
    messages = []
    for error in exc.errors():
        loc = ".".join(str(part) for part in error["loc"])
        messages.append(f"{loc}: {error['msg']}")
    return messages


def _issue_errors(
    issue: AIReviewIssue,
    valid_file_paths: set[str],
    changed_files_by_path: dict[str, ChangedFile],
    valid_context_ids: set[str],
    allowed_categories: set[str] | None,
) -> list[str]:
    errors: list[str] = []
    if allowed_categories is not None and issue.category not in allowed_categories:
        errors.append(
            f"issue category '{issue.category}' is outside this reviewer's scope "
            f"({', '.join(sorted(allowed_categories))})"
        )
        return errors
    if issue.file not in valid_file_paths:
        errors.append(f"issue references a file not shown in the review: {issue.file}")
        return errors

    changed_file = changed_files_by_path.get(issue.file)
    patch = changed_file.patch if changed_file else None
    if not patch:
        errors.append(f"issue references a file with no available patch: {issue.file}")
        return errors

    added_lines = map_added_lines(patch)
    if issue.start_line not in added_lines:
        errors.append(
            f"issue references {issue.file}:{issue.start_line}, which is not an added "
            "line in that file's patch"
        )

    for context_ref in issue.context_refs:
        if context_ref not in valid_context_ids:
            errors.append(
                f"issue references context id not shown in the review: {context_ref}"
            )
    return errors


def _truncate_to_max_issues(
    issues: list[AIReviewIssue], max_issues: int
) -> list[AIReviewIssue]:
    if len(issues) <= max_issues:
        return issues
    return sorted(issues, key=lambda issue: issue.severity_rank)[:max_issues]


def validate_review_output(
    raw: dict[str, Any] | None,
    valid_file_paths: set[str],
    changed_files_by_path: dict[str, ChangedFile],
    max_issues: int,
    valid_context_ids: set[str] | None = None,
    allowed_categories: set[str] | None = None,
) -> tuple[AIReviewOutput | None, list[str]]:
    """Validate raw model output against the Phase 6 contract plus the
    evidence requirements the schema alone can't express.

    Any invalid issue (bad enum caught by pydantic, a file that wasn't shown
    to the model, a line number that isn't actually an added line, or - for
    a specialized reviewer (Phase 14) - a category outside its allowed set)
    invalidates the whole output so the caller can trigger one repair retry,
    per the acceptance criteria. An overlong-but-otherwise-valid issue list
    is truncated to the most severe `max_issues` instead of being rejected.

    `allowed_categories=None` (the general reviewer's default) means no
    category restriction is enforced.
    """
    if raw is None:
        return None, ["model produced no parseable output"]

    try:
        output = AIReviewOutput.model_validate(raw)
    except ValidationError as exc:
        return None, _validation_error_messages(exc)

    context_ids = valid_context_ids or set()
    errors: list[str] = []
    for issue in output.issues:
        errors.extend(
            _issue_errors(
                issue, valid_file_paths, changed_files_by_path, context_ids, allowed_categories
            )
        )
    if errors:
        return None, errors

    if len(output.issues) > max_issues:
        output = output.model_copy(
            update={"issues": _truncate_to_max_issues(output.issues, max_issues)}
        )

    return output, []
