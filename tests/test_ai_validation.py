from app.ai.validation import validate_review_output
from app.models import ChangedFile

_PATCH = "@@ -1,3 +1,4 @@\n context1\n-removed1\n+added1\n+added2\n context2"


def _changed_file(path: str, patch: str = _PATCH) -> ChangedFile:
    return ChangedFile(new_path=path, old_path=path, status="modified", patch=patch)


def _valid_raw(**overrides) -> dict:
    base = dict(
        summary="ok",
        risk="low",
        confidence=0.9,
        decision="approve",
        issues=[
            {
                "file": "src/app.py",
                "start_line": 2,
                "end_line": 2,
                "severity": "high",
                "category": "security",
                "title": "issue",
                "evidence": "evidence text",
                "recommendation": "fix it",
            }
        ],
    )
    base.update(overrides)
    return base


def test_valid_output_with_real_added_line_passes() -> None:
    changed_files = {"src/app.py": _changed_file("src/app.py")}
    output, errors = validate_review_output(
        _valid_raw(), {"src/app.py"}, changed_files, max_issues=50
    )
    assert errors == []
    assert output is not None
    assert output.issues[0].file == "src/app.py"


def test_none_raw_is_invalid() -> None:
    output, errors = validate_review_output(None, set(), {}, max_issues=50)
    assert output is None
    assert errors


def test_nonexistent_file_invalidates_whole_output() -> None:
    changed_files = {"src/app.py": _changed_file("src/app.py")}
    raw = _valid_raw(issues=[{**_valid_raw()["issues"][0], "file": "src/does_not_exist.py"}])
    output, errors = validate_review_output(raw, {"src/app.py"}, changed_files, max_issues=50)
    assert output is None
    assert any("does_not_exist" in e for e in errors)


def test_fabricated_line_number_invalidates_whole_output() -> None:
    changed_files = {"src/app.py": _changed_file("src/app.py")}
    raw = _valid_raw(issues=[{**_valid_raw()["issues"][0], "start_line": 999, "end_line": 999}])
    output, errors = validate_review_output(raw, {"src/app.py"}, changed_files, max_issues=50)
    assert output is None
    assert any("999" in e for e in errors)


def test_bad_enum_invalidates_whole_output() -> None:
    raw = _valid_raw(risk="catastrophic")
    output, errors = validate_review_output(raw, {"src/app.py"}, {}, max_issues=50)
    assert output is None
    assert errors


def test_valid_context_ref_passes() -> None:
    changed_files = {"src/app.py": _changed_file("src/app.py")}
    raw = _valid_raw(issues=[{**_valid_raw()["issues"][0], "context_refs": ["ctx-1"]}])
    output, errors = validate_review_output(
        raw, {"src/app.py"}, changed_files, max_issues=50, valid_context_ids={"ctx-1"}
    )
    assert errors == []
    assert output is not None
    assert output.issues[0].context_refs == ["ctx-1"]


def test_unknown_context_ref_invalidates_whole_output() -> None:
    changed_files = {"src/app.py": _changed_file("src/app.py")}
    raw = _valid_raw(issues=[{**_valid_raw()["issues"][0], "context_refs": ["ctx-99"]}])
    output, errors = validate_review_output(
        raw, {"src/app.py"}, changed_files, max_issues=50, valid_context_ids={"ctx-1"}
    )
    assert output is None
    assert any("ctx-99" in e for e in errors)


def test_context_ref_without_context_available_invalidates_output() -> None:
    changed_files = {"src/app.py": _changed_file("src/app.py")}
    raw = _valid_raw(issues=[{**_valid_raw()["issues"][0], "context_refs": ["ctx-1"]}])
    output, errors = validate_review_output(raw, {"src/app.py"}, changed_files, max_issues=50)
    assert output is None
    assert any("ctx-1" in e for e in errors)


def test_allowed_categories_none_permits_any_category() -> None:
    changed_files = {"src/app.py": _changed_file("src/app.py")}
    output, errors = validate_review_output(
        _valid_raw(), {"src/app.py"}, changed_files, max_issues=50, allowed_categories=None
    )
    assert errors == []
    assert output is not None


def test_issue_outside_allowed_categories_invalidates_whole_output() -> None:
    changed_files = {"src/app.py": _changed_file("src/app.py")}
    output, errors = validate_review_output(
        _valid_raw(), {"src/app.py"}, changed_files, max_issues=50,
        allowed_categories={"performance", "concurrency"},
    )
    assert output is None
    assert any("outside this reviewer's scope" in e for e in errors)


def test_issue_within_allowed_categories_passes() -> None:
    changed_files = {"src/app.py": _changed_file("src/app.py")}
    output, errors = validate_review_output(
        _valid_raw(), {"src/app.py"}, changed_files, max_issues=50,
        allowed_categories={"security", "correctness"},
    )
    assert errors == []
    assert output is not None


def test_oversized_issue_list_truncated_to_most_severe() -> None:
    changed_files = {"src/app.py": _changed_file("src/app.py")}
    severities = ["low", "medium", "high", "critical"]
    issues = [
        {
            "file": "src/app.py",
            "start_line": 2,
            "end_line": 2,
            "severity": sev,
            "category": "security",
            "title": f"issue-{sev}",
            "evidence": "evidence",
            "recommendation": "",
        }
        for sev in severities
    ]
    raw = _valid_raw(issues=issues)

    output, errors = validate_review_output(
        raw, {"src/app.py"}, changed_files, max_issues=2
    )

    assert errors == []
    assert output is not None
    assert len(output.issues) == 2
    assert {issue.severity for issue in output.issues} == {"critical", "high"}
