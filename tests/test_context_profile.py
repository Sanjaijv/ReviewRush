from pathlib import Path

from app.context.profile import build_repo_profile


def test_detects_languages_manifests_frameworks_and_tests(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("def f():\n    pass\n")
    (tmp_path / "src" / "app.js").write_text("function f() {}\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_app.py").write_text("def test_f():\n    pass\n")
    (tmp_path / "pyproject.toml").write_text('dependencies = ["fastapi>=0.115"]\n')
    (tmp_path / "CODEOWNERS").write_text("* @acme/team\n")

    profile = build_repo_profile(tmp_path, max_files_scanned=1000)

    assert profile.languages.get("Python") == 2  # app.py + test_app.py
    assert profile.languages.get("JavaScript") == 1
    assert "pyproject.toml" in profile.manifests
    assert "FastAPI" in profile.frameworks
    assert "tests" in profile.test_directories
    assert "CODEOWNERS" in profile.ownership_files
    assert profile.scan_truncated is False


def test_ignored_directories_are_skipped(tmp_path: Path) -> None:
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "lib.js").write_text("module.exports = {};\n")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("x = 1\n")

    profile = build_repo_profile(tmp_path, max_files_scanned=1000)

    assert profile.languages.get("JavaScript") is None
    assert profile.languages.get("Python") == 1


def test_scan_truncated_when_file_limit_reached(tmp_path: Path) -> None:
    for i in range(5):
        (tmp_path / f"file_{i}.py").write_text("x = 1\n")

    profile = build_repo_profile(tmp_path, max_files_scanned=2)

    assert profile.scan_truncated is True
    assert profile.files_scanned == 2
