from app.models import ChangedFile
from app.reviewers.selection import select_reviewers


def _file(path: str, **overrides) -> ChangedFile:
    base = dict(
        new_path=path, old_path=path, status="modified", additions=1, deletions=0, patch="patch",
    )
    base.update(overrides)
    return ChangedFile(**base)


def _names(changed_files: list[ChangedFile]) -> set[str]:
    return {d.name for d in select_reviewers(changed_files)}


def test_docs_only_change_selects_no_reviewers() -> None:
    assert _names([_file("README.md")]) == set()


def test_excluded_or_patchless_files_are_ignored() -> None:
    excluded = _file("src/app.py", excluded_from_ai=True)
    no_patch = _file("src/other.py", patch=None)
    assert _names([excluded, no_patch]) == set()


def test_plain_code_change_selects_security_logic_and_test_quality() -> None:
    names = _names([_file("src/app.py", additions=2, deletions=1)])
    assert "security" in names
    assert "logic_correctness" in names
    assert "test_quality" in names
    assert "performance_concurrency" not in names
    assert "architecture_maintainability" not in names


def test_auth_path_selects_security_even_for_non_code_extension() -> None:
    names = _names([_file("config/auth.yaml", additions=2)])
    assert "security" in names


def test_large_change_selects_performance_concurrency() -> None:
    names = _names([_file("src/app.py", additions=20, deletions=15)])
    assert "performance_concurrency" in names


def test_worker_path_selects_performance_concurrency_regardless_of_size() -> None:
    names = _names([_file("app/tasks/worker.py", additions=1, deletions=0)])
    assert "performance_concurrency" in names


def test_many_files_selects_architecture_maintainability() -> None:
    files = [_file(f"src/mod_{i}.py") for i in range(5)]
    assert "architecture_maintainability" in _names(files)


def test_added_code_file_selects_architecture_maintainability() -> None:
    names = _names([_file("src/new_module.py", status="added")])
    assert "architecture_maintainability" in names
