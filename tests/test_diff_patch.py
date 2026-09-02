from app.diffs.patch import map_added_lines, parse_patch


def test_parse_patch_tracks_old_and_new_line_numbers() -> None:
    patch = "@@ -1,3 +1,4 @@\n context1\n-removed1\n+added1\n+added2\n context2"
    hunks = parse_patch(patch)

    assert len(hunks) == 1
    hunk = hunks[0]
    assert (hunk.old_start, hunk.old_lines) == (1, 3)
    assert (hunk.new_start, hunk.new_lines) == (1, 4)

    origins = [(line.origin, line.old_lineno, line.new_lineno) for line in hunk.lines]
    assert origins == [
        (" ", 1, 1),
        ("-", 2, None),
        ("+", None, 2),
        ("+", None, 3),
        (" ", 3, 4),
    ]


def test_map_added_lines_returns_diff_positions() -> None:
    patch = "@@ -1,3 +1,4 @@\n context1\n-removed1\n+added1\n+added2\n context2"
    assert map_added_lines(patch) == {2: 4, 3: 5}


def test_map_added_lines_across_multiple_hunks_keeps_running_position() -> None:
    patch = (
        "@@ -1,2 +1,2 @@\n"
        " a\n"
        "-b\n"
        "+b2\n"
        "@@ -10,2 +10,3 @@\n"
        " x\n"
        "+y\n"
        " z"
    )
    mapping = map_added_lines(patch)
    assert mapping == {2: 4, 11: 7}


def test_parse_patch_handles_pure_deletion() -> None:
    patch = "@@ -1,2 +0,0 @@\n-line one\n-line two"
    hunks = parse_patch(patch)
    assert len(hunks) == 1
    assert all(line.origin == "-" for line in hunks[0].lines)
    assert map_added_lines(patch) == {}


def test_parse_patch_ignores_no_newline_marker() -> None:
    patch = (
        "@@ -1,1 +1,1 @@\n-old\n\\ No newline at end of file\n"
        "+new\n\\ No newline at end of file"
    )
    hunks = parse_patch(patch)
    assert len(hunks[0].lines) == 2


def test_parse_patch_empty_string_returns_no_hunks() -> None:
    assert parse_patch("") == []


def test_parse_patch_ignores_content_before_first_hunk_header() -> None:
    patch = "garbage preamble\n@@ -1,1 +1,1 @@\n-a\n+b"
    hunks = parse_patch(patch)
    assert len(hunks) == 1
    assert len(hunks[0].lines) == 2
