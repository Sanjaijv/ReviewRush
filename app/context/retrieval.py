"""Retrieval of code related to a diff's changed symbols: callers/references,
tests, and nearby config, plus incremental maintenance of `RepoFileIndex`.

Everything here is lexical/structural (path conventions, regex/grep, and the
symbol metadata from `app/context/symbols.py`) per the Phase 10 roadmap's
instruction to start there before adding embeddings. Every snippet of code
text handed back is read live from the caller-supplied workspace checkout
of one specific head_sha - `RepoFileIndex` only ever supplies which paths
to look at, never the text itself - so retrieved content can never mix
commits.
"""

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.context.profile import IGNORED_DIR_NAMES
from app.context.symbols import Symbol, detect_language, extract_symbols
from app.diffs.patch import parse_patch
from app.models import ChangedFile, RepoFileIndex

_SNIPPET_CONTEXT_LINES = 4
_TEST_PATH_PATTERN = re.compile(
    r"(^|/)(tests?|__tests__|spec)(/|$)|(^|/)test_[^/]+$|_test\.\w+$|\.test\.\w+$|\.spec\.\w+$",
    re.IGNORECASE,
)
_CONFIG_NAME_PATTERN = re.compile(
    r"^(schema|settings|config)\b.*\.(py|json|ya?ml|toml)$", re.IGNORECASE
)


@dataclass
class ContextItem:
    id: str
    path: str
    kind: str  # "definition" | "reference" | "test" | "config" | "guidance"
    symbol: str | None
    start_line: int
    end_line: int
    snippet: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "path": self.path,
            "kind": self.kind,
            "symbol": self.symbol,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "snippet": self.snippet,
            "reason": self.reason,
        }


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _changed_new_line_numbers(patch: str) -> set[int]:
    lines: set[int] = set()
    for hunk in parse_patch(patch):
        for line in hunk.lines:
            if line.origin == "+" and line.new_lineno is not None:
                lines.add(line.new_lineno)
    return lines


def _symbols_touching_lines(symbols: list[Symbol], changed_lines: set[int]) -> list[Symbol]:
    return [
        symbol
        for symbol in symbols
        if any(symbol.start_line <= n <= symbol.end_line for n in changed_lines)
    ]


def _read_file(path: Path, max_bytes: int) -> str | None:
    try:
        if path.stat().st_size > max_bytes:
            return None
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def reindex_changed_files(
    db: Any,
    repository_id: int,
    workspace_root: Path,
    changed_files: list[ChangedFile],
    head_sha: str,
    max_file_bytes: int,
    max_symbols_per_file: int,
) -> dict[str, list[Symbol]]:
    """Re-parse symbols for exactly the files this diff touched, upserting
    `RepoFileIndex`. Files untouched by this diff keep their existing index
    row unread and unmodified - the "re-index only changed files" behavior
    the roadmap calls for. Returns the subset of each changed file's symbols
    whose line range overlaps an added line, keyed by path.
    """
    changed_symbols_by_path: dict[str, list[Symbol]] = {}

    for changed_file in changed_files:
        if changed_file.status == "removed":
            old_path = changed_file.old_path
            if old_path:
                db.query(RepoFileIndex).filter_by(
                    repository_id=repository_id, path=old_path
                ).delete()
            continue

        path = changed_file.new_path or changed_file.old_path
        if not path:
            continue

        content = _read_file(workspace_root / path, max_file_bytes)
        if content is None:
            continue

        content_sha = _sha256_hex(content.encode("utf-8", errors="replace"))
        all_symbols = extract_symbols(path, content, max_symbols_per_file)

        row = (
            db.query(RepoFileIndex)
            .filter_by(repository_id=repository_id, path=path)
            .one_or_none()
        )
        if row is None:
            row = RepoFileIndex(repository_id=repository_id, path=path)
            db.add(row)
        row.content_sha = content_sha
        row.language = detect_language(path)
        row.symbols = [
            {"name": s.name, "kind": s.kind, "start_line": s.start_line, "end_line": s.end_line}
            for s in all_symbols
        ]
        row.last_seen_commit_sha = head_sha

        if changed_file.patch and not changed_file.content_fetched:
            changed_lines = _changed_new_line_numbers(changed_file.patch)
            changed_symbols_by_path[path] = _symbols_touching_lines(all_symbols, changed_lines)
        elif changed_file.status == "added":
            # A brand-new file has no "changed lines" mapping to anchor
            # against - every symbol in it is new.
            changed_symbols_by_path[path] = all_symbols

    return changed_symbols_by_path


def snippet_for_range(
    content_lines: list[str], start_line: int, end_line: int
) -> tuple[str, int, int]:
    lo = max(1, start_line - _SNIPPET_CONTEXT_LINES)
    hi = min(len(content_lines), end_line + _SNIPPET_CONTEXT_LINES)
    snippet = "\n".join(content_lines[lo - 1 : hi])
    return snippet, lo, hi


def iter_source_files(workspace_root: Path, max_files_scanned: int) -> list[Path]:
    files: list[Path] = []
    for path in workspace_root.rglob("*"):
        if len(files) >= max_files_scanned:
            break
        if not path.is_file():
            continue
        relative = path.relative_to(workspace_root)
        if any(part in IGNORED_DIR_NAMES for part in relative.parts):
            continue
        files.append(path)
    return files


def _find_matches(
    workspace_root: Path,
    candidate_files: list[Path],
    symbol_name: str,
    exclude_path: str,
    max_results: int,
    max_file_bytes: int,
    path_filter: "re.Pattern | None" = None,
) -> list[tuple[str, int, list[str]]]:
    pattern = re.compile(r"\b" + re.escape(symbol_name) + r"\b")
    matches: list[tuple[str, int, list[str]]] = []

    for path in candidate_files:
        relative_str = str(path.relative_to(workspace_root))
        if relative_str == exclude_path:
            continue
        if path_filter is not None and not path_filter.search(relative_str):
            continue
        content = _read_file(path, max_file_bytes)
        if content is None:
            continue
        content_lines = content.splitlines()
        for lineno, line in enumerate(content_lines, start=1):
            if pattern.search(line):
                matches.append((relative_str, lineno, content_lines))
                break
        if len(matches) >= max_results:
            break

    return matches


def build_context_items_for_symbol(
    workspace_root: Path,
    path: str,
    symbol: Symbol,
    all_source_files: list[Path],
    max_items_per_symbol: int,
    max_file_bytes: int,
) -> list[ContextItem]:
    """Build the definition item plus reference/test items for one changed
    symbol. `path`/`symbol` describe where the symbol is *defined* in the
    current diff; everything else is found by lexical search of the fresh
    workspace checkout.
    """
    items: list[ContextItem] = []

    def_content = _read_file(workspace_root / path, max_file_bytes)
    if def_content is not None:
        def_lines = def_content.splitlines()
        snippet, lo, hi = snippet_for_range(def_lines, symbol.start_line, symbol.end_line)
        items.append(
            ContextItem(
                id="",
                path=path,
                kind="definition",
                symbol=symbol.name,
                start_line=lo,
                end_line=hi,
                snippet=snippet,
                reason=f"changed definition of {symbol.kind} '{symbol.name}'",
            )
        )

    references = _find_matches(
        workspace_root,
        all_source_files,
        symbol.name,
        exclude_path=path,
        max_results=max_items_per_symbol,
        max_file_bytes=max_file_bytes,
    )
    for relative_str, lineno, content_lines in references:
        if _TEST_PATH_PATTERN.search(relative_str):
            continue  # tests are retrieved separately, tagged as "test"
        snippet, lo, hi = snippet_for_range(content_lines, lineno, lineno)
        items.append(
            ContextItem(
                id="",
                path=relative_str,
                kind="reference",
                symbol=symbol.name,
                start_line=lo,
                end_line=hi,
                snippet=snippet,
                reason=f"references '{symbol.name}', changed in {path}",
            )
        )

    tests = _find_matches(
        workspace_root,
        all_source_files,
        symbol.name,
        exclude_path=path,
        max_results=max_items_per_symbol,
        max_file_bytes=max_file_bytes,
        path_filter=_TEST_PATH_PATTERN,
    )
    for relative_str, lineno, content_lines in tests:
        snippet, lo, hi = snippet_for_range(content_lines, lineno, lineno)
        items.append(
            ContextItem(
                id="",
                path=relative_str,
                kind="test",
                symbol=symbol.name,
                start_line=lo,
                end_line=hi,
                snippet=snippet,
                reason=f"test referencing '{symbol.name}', changed in {path}",
            )
        )

    return items


def find_config_items(
    workspace_root: Path, changed_path: str, max_items: int, max_file_bytes: int
) -> list[ContextItem]:
    directory = (workspace_root / changed_path).parent
    if not directory.is_dir():
        return []

    items: list[ContextItem] = []
    for candidate in sorted(directory.iterdir()):
        if len(items) >= max_items:
            break
        if not candidate.is_file() or str(candidate.relative_to(workspace_root)) == changed_path:
            continue
        if not _CONFIG_NAME_PATTERN.match(candidate.name):
            continue
        content = _read_file(candidate, max_file_bytes)
        if content is None:
            continue
        relative_str = str(candidate.relative_to(workspace_root))
        content_lines = content.splitlines()
        snippet = "\n".join(content_lines[:40])
        items.append(
            ContextItem(
                id="",
                path=relative_str,
                kind="config",
                symbol=None,
                start_line=1,
                end_line=min(40, len(content_lines)),
                snippet=snippet,
                reason=f"configuration near changed file {changed_path}",
            )
        )
    return items


def apply_budget(
    items: list[ContextItem], max_bytes: int
) -> tuple[list[ContextItem], bool, int]:
    """Keep items in the given order - the caller's relevance ranking
    (app/context/rerank.py's `rerank`, highest-relevance first) as of
    Phase 11 - until `max_bytes` is exhausted, then assign stable ids in the
    kept order so `AIFinding.context_refs` can address them.

    An item larger than the remaining budget is skipped in favor of trying
    smaller lower-ranked items after it, so one oversized high-relevance hit
    can't crowd out everything behind it.
    """
    kept: list[ContextItem] = []
    used_bytes = 0
    truncated = False

    for item in items:
        size = len(item.snippet.encode("utf-8"))
        if used_bytes + size > max_bytes:
            truncated = True
            continue
        used_bytes += size
        kept.append(item)

    for index, item in enumerate(kept, start=1):
        item.id = f"ctx-{index}"

    return kept, truncated, used_bytes
