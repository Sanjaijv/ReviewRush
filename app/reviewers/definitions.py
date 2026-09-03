from collections.abc import Callable
from dataclasses import dataclass

from app.models import ChangedFile

# Extensions treated as "real logic changed" rather than docs/config/data.
# Deliberately broad and conservative (false positives just mean an extra,
# bounded-cost specialist pass; false negatives mean a category of bug goes
# unchecked), matching the roadmap's "run selectively, not on every change"
# instruction without trying to be clever about it.
_CODE_EXTENSIONS = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".rb", ".php", ".java",
    ".kt", ".rs", ".c", ".cc", ".cpp", ".h", ".hpp", ".cs", ".sql", ".sh",
    ".scala", ".swift",
}

_SECURITY_PATH_KEYWORDS = (
    "auth", "authn", "authz", "secret", "token", "password", "crypto",
    "payment", "billing", "session", "jwt", "oauth", "permission", "acl",
    "sql", "inject", "credential",
)

_CONCURRENCY_PATH_KEYWORDS = (
    "worker", "task", "queue", "async", "thread", "lock", "cache",
    "concurrent", "pool", "celery",
)

_TEST_PATH_KEYWORDS = ("test", "spec")

# Total changed lines (across reviewable code files) above which a diff is
# considered large enough to warrant the performance/concurrency pass even
# without a path-based signal.
_LARGE_CHANGE_LINE_THRESHOLD = 30
# File count above which a diff is considered structural/multi-file enough
# to warrant the architecture/maintainability pass.
_MULTI_FILE_THRESHOLD = 5


def _path(changed_file: ChangedFile) -> str:
    return changed_file.new_path or changed_file.old_path or ""


def _extension(path: str) -> str:
    dot = path.rfind(".")
    return path[dot:].lower() if dot != -1 else ""


def _reviewable(changed_file: ChangedFile) -> bool:
    return not changed_file.excluded_from_ai and bool(changed_file.patch)


def _is_code_file(changed_file: ChangedFile) -> bool:
    return _extension(_path(changed_file)) in _CODE_EXTENSIONS


def _path_contains_any(changed_file: ChangedFile, keywords: tuple[str, ...]) -> bool:
    path = _path(changed_file).lower()
    return any(keyword in path for keyword in keywords)


def _select_security(changed_files: list[ChangedFile]) -> bool:
    reviewable = [f for f in changed_files if _reviewable(f)]
    return any(
        _is_code_file(f) or _path_contains_any(f, _SECURITY_PATH_KEYWORDS)
        for f in reviewable
    )


def _select_logic_correctness(changed_files: list[ChangedFile]) -> bool:
    return any(_is_code_file(f) for f in changed_files if _reviewable(f))


def _select_performance_concurrency(changed_files: list[ChangedFile]) -> bool:
    reviewable_code = [f for f in changed_files if _reviewable(f) and _is_code_file(f)]
    if not reviewable_code:
        return False
    if any(_path_contains_any(f, _CONCURRENCY_PATH_KEYWORDS) for f in reviewable_code):
        return True
    total_lines = sum(f.additions + f.deletions for f in reviewable_code)
    return total_lines >= _LARGE_CHANGE_LINE_THRESHOLD


def _select_architecture_maintainability(changed_files: list[ChangedFile]) -> bool:
    reviewable = [f for f in changed_files if _reviewable(f)]
    if len(reviewable) >= _MULTI_FILE_THRESHOLD:
        return True
    return any(f.status in ("added", "removed") for f in reviewable if _is_code_file(f))


def _select_test_quality(changed_files: list[ChangedFile]) -> bool:
    return any(_is_code_file(f) for f in changed_files if _reviewable(f))


@dataclass(frozen=True)
class ReviewerDefinition:
    """One specialized reviewer role (Phase 14).

    `categories` restricts both the prompt (what it's told to look for) and
    validation (any issue outside these categories invalidates the output,
    same as an unshown file path does for the general reviewer) - a
    specialist can never smuggle out-of-scope findings through just by the
    model ignoring instructions.

    `selector` is a pure predicate over the diff's changed files, so which
    reviewers run for a given change is deterministic and independently
    testable without calling a model.
    """

    name: str
    focus: str
    categories: tuple[str, ...]
    selector: Callable[[list[ChangedFile]], bool]


REVIEWER_DEFINITIONS: tuple[ReviewerDefinition, ...] = (
    ReviewerDefinition(
        name="security",
        focus=(
            "Security vulnerabilities: injection, authN/authZ flaws, secrets "
            "handling, unsafe deserialization, SSRF, path traversal, and "
            "other OWASP-class issues."
        ),
        categories=("security",),
        selector=_select_security,
    ),
    ReviewerDefinition(
        name="logic_correctness",
        focus=(
            "Logic and correctness bugs, and missing or incorrect error "
            "handling."
        ),
        categories=("correctness", "error_handling"),
        selector=_select_logic_correctness,
    ),
    ReviewerDefinition(
        name="performance_concurrency",
        focus=(
            "Performance regressions (N+1 queries, unnecessary work in hot "
            "paths, unbounded growth) and concurrency hazards (races, "
            "deadlocks, unsafe shared state)."
        ),
        categories=("performance", "concurrency"),
        selector=_select_performance_concurrency,
    ),
    ReviewerDefinition(
        name="architecture_maintainability",
        focus=(
            "Architecture and maintainability: unnecessary complexity, poor "
            "separation of concerns, and backward-compatibility risks."
        ),
        categories=("maintainability", "compatibility"),
        selector=_select_architecture_maintainability,
    ),
    ReviewerDefinition(
        name="test_quality",
        focus=(
            "Test quality: missing tests for new behavior, and tests that "
            "don't actually exercise the change."
        ),
        categories=("missing_tests",),
        selector=_select_test_quality,
    ),
)
