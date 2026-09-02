import re
from dataclasses import dataclass, field

_HUNK_HEADER = re.compile(r"^@@ -(?P<old_start>\d+)(?:,(?P<old_lines>\d+))? "
                           r"\+(?P<new_start>\d+)(?:,(?P<new_lines>\d+))? @@")


@dataclass
class DiffLine:
    """One line of a hunk. `origin` is '+' (added), '-' (removed), or ' ' (context).

    `position` is the line's 1-indexed offset into the *whole* per-file patch
    text (counting every patch line, including "@@" headers), matching the
    `position` value GitHub's pull request review comment API expects.
    """

    origin: str
    content: str
    old_lineno: int | None
    new_lineno: int | None
    position: int


@dataclass
class Hunk:
    old_start: int
    old_lines: int
    new_start: int
    new_lines: int
    header: str
    lines: list[DiffLine] = field(default_factory=list)


def parse_patch(patch: str) -> list[Hunk]:
    """Parse a unified-diff patch body (as returned by GitHub's compare API,
    i.e. no `--- a/...`/`+++ b/...` file headers, just `@@` hunks) into
    structured hunks with per-line old/new line numbers and diff positions.

    Malformed or unrecognized lines are ignored rather than raising, so a
    patch with unexpected content degrades to partial output instead of
    crashing the pipeline.
    """
    hunks: list[Hunk] = []
    current: Hunk | None = None
    old_line = 0
    new_line = 0

    for position, raw_line in enumerate(patch.splitlines(), start=1):
        header_match = _HUNK_HEADER.match(raw_line)
        if header_match:
            old_start = int(header_match.group("old_start"))
            new_start = int(header_match.group("new_start"))
            current = Hunk(
                old_start=old_start,
                old_lines=int(header_match.group("old_lines") or 1),
                new_start=new_start,
                new_lines=int(header_match.group("new_lines") or 1),
                header=raw_line,
            )
            hunks.append(current)
            old_line = old_start
            new_line = new_start
            continue

        if current is None:
            continue

        if raw_line.startswith("+"):
            current.lines.append(
                DiffLine(
                    origin="+",
                    content=raw_line[1:],
                    old_lineno=None,
                    new_lineno=new_line,
                    position=position,
                )
            )
            new_line += 1
        elif raw_line.startswith("-"):
            current.lines.append(
                DiffLine(
                    origin="-",
                    content=raw_line[1:],
                    old_lineno=old_line,
                    new_lineno=None,
                    position=position,
                )
            )
            old_line += 1
        elif raw_line.startswith("\\"):
            # "\ No newline at end of file" - not a content line.
            continue
        else:
            current.lines.append(
                DiffLine(
                    origin=" ",
                    content=raw_line[1:] if raw_line.startswith(" ") else raw_line,
                    old_lineno=old_line,
                    new_lineno=new_line,
                    position=position,
                )
            )
            old_line += 1
            new_line += 1

    return hunks


def map_added_lines(patch: str) -> dict[int, int]:
    """Return {new_file_line_number: diff_position} for every added ('+') line
    in the patch. Used to translate an AI/tool finding's line number into the
    position GitHub's review comment API requires.
    """
    mapping: dict[int, int] = {}
    for hunk in parse_patch(patch):
        for line in hunk.lines:
            if line.origin == "+" and line.new_lineno is not None:
                mapping[line.new_lineno] = line.position
    return mapping
