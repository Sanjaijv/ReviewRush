from app.ai.prompt import SYSTEM_PROMPT, build_review_prompt
from app.config import Settings
from app.models import ChangedFile, DiffSnapshot, RepoContextSnapshot, ToolRun
from app.repo_config import parse_repo_config


class _FakeRepository:
    def __init__(self) -> None:
        self.full_name = "acme/widgets"


def _settings(**overrides) -> Settings:
    base = dict(ai_max_prompt_bytes=400_000)
    base.update(overrides)
    return Settings(**base)


def test_system_prompt_marks_diff_content_as_untrusted_data() -> None:
    assert "UNTRUSTED DATA" in SYSTEM_PROMPT
    assert "not instructions" in SYSTEM_PROMPT


def test_excluded_file_shows_path_and_reason_not_content() -> None:
    diff_snapshot = DiffSnapshot(id=1, repository_id=1, head_sha="sha1", base_sha="mainsha")
    binary_file = ChangedFile(
        new_path="assets/logo.png",
        old_path="assets/logo.png",
        status="modified",
        is_binary=True,
        excluded_from_ai=True,
    )
    text_file = ChangedFile(
        new_path="src/app.py",
        old_path="src/app.py",
        status="modified",
        additions=2,
        deletions=0,
        patch="@@ -1,1 +1,3 @@\n context\n+included_marker\n+more",
    )

    result = build_review_prompt(
        repository=_FakeRepository(),
        diff_snapshot=diff_snapshot,
        changed_files=[binary_file, text_file],
        tool_runs=[],
        repo_config=parse_repo_config(None),
        settings=_settings(),
    )

    assert "assets/logo.png" in result.user
    assert "binary file" in result.user
    assert "src/app.py" in result.user
    assert "included_marker" in result.user  # the non-excluded file's patch is shown
    assert result.valid_file_paths == {"src/app.py"}
    assert result.truncated is False


def test_prompt_byte_budget_omits_files_and_marks_truncated() -> None:
    diff_snapshot = DiffSnapshot(id=1, repository_id=1, head_sha="sha1", base_sha="mainsha")
    big_patch = "@@ -1,1 +1,2 @@\n context\n+" + ("x" * 5000)
    small_patch = "@@ -1,1 +1,2 @@\n context\n+y"

    small_file = ChangedFile(
        new_path="small.py", old_path="small.py", status="modified", patch=small_patch
    )
    big_file = ChangedFile(
        new_path="big.py", old_path="big.py", status="modified", patch=big_patch
    )

    result = build_review_prompt(
        repository=_FakeRepository(),
        diff_snapshot=diff_snapshot,
        changed_files=[big_file, small_file],
        tool_runs=[],
        repo_config=parse_repo_config(None),
        settings=_settings(ai_max_prompt_bytes=500),
    )

    assert result.truncated is True
    assert "small.py" in result.valid_file_paths
    assert "big.py" not in result.valid_file_paths
    assert "omitted, prompt size budget" in result.user


def test_no_context_snapshot_notes_unavailable() -> None:
    diff_snapshot = DiffSnapshot(id=1, repository_id=1, head_sha="sha1", base_sha="mainsha")

    result = build_review_prompt(
        repository=_FakeRepository(),
        diff_snapshot=diff_snapshot,
        changed_files=[],
        tool_runs=[],
        repo_config=parse_repo_config(None),
        settings=_settings(),
    )

    assert "Repository context" in result.user
    assert "not available for this review" in result.user
    assert result.valid_context_ids == set()


def test_context_snapshot_items_are_shown_with_ids_and_marked_untrusted() -> None:
    diff_snapshot = DiffSnapshot(id=1, repository_id=1, head_sha="sha1", base_sha="mainsha")
    context_snapshot = RepoContextSnapshot(
        id=1,
        repository_id=1,
        diff_snapshot_id=1,
        profile={"languages": {"Python": 3}, "frameworks": ["FastAPI"]},
        guidance=[{"path": "AGENTS.md", "content": "Follow PEP 8.", "truncated": False}],
        context_items=[
            {
                "id": "ctx-1",
                "path": "src/helpers.py",
                "kind": "reference",
                "symbol": "helper",
                "start_line": 1,
                "end_line": 3,
                "snippet": "def helper():\n    return 1",
                "reason": "references 'helper', changed in src/app.py",
            }
        ],
        truncated=False,
    )

    result = build_review_prompt(
        repository=_FakeRepository(),
        diff_snapshot=diff_snapshot,
        changed_files=[],
        tool_runs=[],
        repo_config=parse_repo_config(None),
        settings=_settings(),
        context_snapshot=context_snapshot,
    )

    assert "[ctx-1]" in result.user
    assert "src/helpers.py" in result.user
    assert "FastAPI" in result.user
    assert "Follow PEP 8." in result.user
    assert result.valid_context_ids == {"ctx-1"}
    assert "Repository context" in SYSTEM_PROMPT or "Repository context" in result.user


def test_tool_run_summaries_included() -> None:
    diff_snapshot = DiffSnapshot(id=1, repository_id=1, head_sha="sha1", base_sha="mainsha")
    tool_run = ToolRun(
        repository_id=1,
        diff_snapshot_id=1,
        check_name="tests",
        category="test",
        conclusion="failed",
        summary="2 tests failed",
    )

    result = build_review_prompt(
        repository=_FakeRepository(),
        diff_snapshot=diff_snapshot,
        changed_files=[],
        tool_runs=[tool_run],
        repo_config=parse_repo_config(None),
        settings=_settings(),
    )

    assert "tests (test): failed - 2 tests failed" in result.user
