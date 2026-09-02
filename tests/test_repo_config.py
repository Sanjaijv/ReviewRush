from app.repo_config import RepoConfig, parse_repo_config


def test_none_yields_defaults() -> None:
    config = parse_repo_config(None)
    assert config == RepoConfig()
    assert config.branches.source is None
    assert config.merge.enabled is False


def test_empty_string_yields_defaults() -> None:
    assert parse_repo_config("") == RepoConfig()
    assert parse_repo_config("   \n") == RepoConfig()


def test_valid_config_is_parsed() -> None:
    raw = """
version: 1
branches:
  source: foundations
  target: main
review:
  minimum_ai_confidence: 0.8
protected_paths:
  - "src/auth/**"
checks:
  tests:
    command: "pytest"
    required: true
merge:
  enabled: true
  method: squash
"""
    config = parse_repo_config(raw)
    assert config.branches.source == "foundations"
    assert config.branches.target == "main"
    assert config.review.minimum_ai_confidence == 0.8
    assert config.protected_paths == ["src/auth/**"]
    assert config.checks["tests"].command == "pytest"
    assert config.merge.enabled is True


def test_invalid_yaml_fails_closed_to_defaults() -> None:
    config = parse_repo_config("branches: [this is not: valid: yaml")
    assert config == RepoConfig()


def test_non_mapping_document_fails_closed_to_defaults() -> None:
    config = parse_repo_config("- just\n- a\n- list\n")
    assert config == RepoConfig()


def test_unknown_top_level_key_fails_closed_to_defaults() -> None:
    config = parse_repo_config("version: 1\nnot_a_real_field: true\n")
    assert config == RepoConfig()


def test_invalid_field_type_fails_closed_to_defaults() -> None:
    config = parse_repo_config("branches:\n  source: 123\n")
    assert config == RepoConfig()
