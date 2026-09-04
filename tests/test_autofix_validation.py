from app.autofix.validation import validate_fix_suggestion


def test_valid_applicable_suggestion_passes() -> None:
    suggestion, errors = validate_fix_suggestion(
        {"applicable": True, "replacement_lines": ["    return safe(x)"], "explanation": "fix"}
    )
    assert errors == []
    assert suggestion is not None
    assert suggestion.applicable is True
    assert suggestion.replacement_lines == ["    return safe(x)"]


def test_not_applicable_with_no_replacement_lines_is_valid() -> None:
    suggestion, errors = validate_fix_suggestion(
        {"applicable": False, "replacement_lines": [], "explanation": "needs a wider change"}
    )
    assert errors == []
    assert suggestion is not None
    assert suggestion.applicable is False


def test_applicable_with_empty_replacement_lines_is_rejected() -> None:
    suggestion, errors = validate_fix_suggestion(
        {"applicable": True, "replacement_lines": [], "explanation": ""}
    )
    assert suggestion is None
    assert errors == ["applicable=true but replacement_lines is empty"]


def test_none_input_is_rejected() -> None:
    suggestion, errors = validate_fix_suggestion(None)
    assert suggestion is None
    assert errors == ["model produced no parseable output"]


def test_unknown_extra_field_is_rejected() -> None:
    suggestion, errors = validate_fix_suggestion(
        {
            "applicable": True,
            "replacement_lines": ["x = 1"],
            "explanation": "",
            "unexpected_field": "nope",
        }
    )
    assert suggestion is None
    assert errors


def test_missing_applicable_field_is_rejected() -> None:
    suggestion, errors = validate_fix_suggestion({"replacement_lines": ["x = 1"]})
    assert suggestion is None
    assert errors
