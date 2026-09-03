from app.policy.paths import matches_any


def test_no_patterns_returns_none() -> None:
    assert matches_any("src/auth/login.py", []) is None


def test_empty_path_returns_none() -> None:
    assert matches_any("", ["**/auth/**"]) is None


def test_double_star_matches_nested_path() -> None:
    assert matches_any("src/auth/login.py", ["src/auth/**"]) == "src/auth/**"


def test_non_matching_path_returns_none() -> None:
    assert matches_any("src/app.py", ["src/auth/**", "migrations/**"]) is None


def test_first_matching_pattern_is_returned() -> None:
    pattern = matches_any(".reviewrush.yml", ["*.yml", ".reviewrush.yml"])
    assert pattern == "*.yml"


def test_exact_filename_pattern() -> None:
    assert matches_any(".reviewrush.yml", [".reviewrush.yml"]) == ".reviewrush.yml"
