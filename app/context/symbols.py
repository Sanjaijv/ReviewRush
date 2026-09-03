"""Per-file top-level symbol extraction.

Symbols are extracted with an exact parser for Python (the stdlib `ast`
module) and lightweight regex heuristics for other common languages. Both
paths only ever produce symbol *metadata* (name, kind, line range) - never
copy code text - so `RepoFileIndex` can safely persist them across commits;
the actual snippet text a review sees is always re-read from that review's
own workspace at render time (see `app/context/retrieval.py`).

This intentionally starts at "lexical and structural retrieval" per the
Phase 10 roadmap rather than depending on a compiled Tree-sitter grammar
per language. `extract_symbols` is the seam a Tree-sitter-backed extractor
could later replace without touching any caller.
"""

import ast
import re
from dataclasses import dataclass
from pathlib import PurePosixPath

_EXTENSION_LANGUAGES: dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".go": "go",
    ".java": "java",
    ".rb": "ruby",
    ".rs": "rust",
}


@dataclass(frozen=True)
class Symbol:
    name: str
    kind: str  # "function" | "method" | "class" | "module"
    start_line: int
    end_line: int


def detect_language(path: str) -> str:
    suffix = PurePosixPath(path).suffix.lower()
    return _EXTENSION_LANGUAGES.get(suffix, "")


def _python_symbols(content: str) -> list[Symbol]:
    try:
        tree = ast.parse(content)
    except (SyntaxError, ValueError):
        # Untrusted PR content may not even parse (e.g. a WIP commit, or a
        # file that isn't actually valid Python despite its extension) -
        # degrade to no symbols rather than raising.
        return []

    symbols: list[Symbol] = []

    def _visit(node: ast.AST, in_class: bool) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                symbols.append(
                    Symbol(
                        name=child.name,
                        kind="class",
                        start_line=child.lineno,
                        end_line=getattr(child, "end_lineno", child.lineno),
                    )
                )
                _visit(child, in_class=True)
            elif isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                symbols.append(
                    Symbol(
                        name=child.name,
                        kind="method" if in_class else "function",
                        start_line=child.lineno,
                        end_line=getattr(child, "end_lineno", child.lineno),
                    )
                )
                # Do not descend into nested functions/methods bodies for
                # further top-level symbols beyond one level of nesting.

    _visit(tree, in_class=False)
    return symbols


def _brace_block_end(lines: list[str], start_idx: int) -> int:
    """Find the 1-indexed line where the `{`-delimited block opened on
    `lines[start_idx]` closes, by naive brace counting (ignores braces
    inside strings/comments). Falls back to the start line if no opening
    brace is found on or after the declaration line within a short window.
    """
    depth = 0
    seen_open = False
    for offset, line in enumerate(lines[start_idx : start_idx + 400]):
        depth += line.count("{")
        depth -= line.count("}")
        if "{" in line:
            seen_open = True
        if seen_open and depth <= 0:
            return start_idx + offset + 1
    return start_idx + 1


_JS_TS_PATTERNS = [
    (re.compile(r"^\s*(?:export\s+(?:default\s+)?)?class\s+([A-Za-z_$][\w$]*)"), "class"),
    (
        re.compile(
            r"^\s*(?:export\s+(?:default\s+)?)?(?:async\s+)?function\s*\*?\s+"
            r"([A-Za-z_$][\w$]*)\s*\("
        ),
        "function",
    ),
    (
        re.compile(
            r"^\s*(?:export\s+)?const\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?"
            r"(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>"
        ),
        "function",
    ),
]

_GO_PATTERNS = [
    (re.compile(r"^\s*func\s+(?:\([^)]*\)\s*)?([A-Za-z_]\w*)\s*\("), "function"),
    (re.compile(r"^\s*type\s+([A-Za-z_]\w*)\s+struct\b"), "class"),
]

_JAVA_PATTERNS = [
    (re.compile(r"^\s*(?:public|private|protected|static|final|\s)*class\s+(\w+)"), "class"),
    (re.compile(r"^\s*(?:public|private|protected|static|final|\s)*interface\s+(\w+)"), "class"),
    (
        re.compile(
            r"^\s*(?:public|private|protected|static|final|synchronized|\s)*"
            r"[\w<>\[\],\s]+\s+(\w+)\s*\([^;{]*\)\s*\{?\s*$"
        ),
        "method",
    ),
]

_RUBY_PATTERNS = [
    (re.compile(r"^\s*class\s+([A-Za-z_]\w*)"), "class"),
    (re.compile(r"^\s*module\s+([A-Za-z_]\w*)"), "class"),
    (re.compile(r"^\s*def\s+(?:self\.)?([A-Za-z_]\w*[?!=]?)"), "function"),
]

_RUST_PATTERNS = [
    (re.compile(r"^\s*(?:pub\s+)?fn\s+([A-Za-z_]\w*)"), "function"),
    (re.compile(r"^\s*(?:pub\s+)?struct\s+([A-Za-z_]\w*)"), "class"),
    (re.compile(r"^\s*(?:pub\s+)?enum\s+([A-Za-z_]\w*)"), "class"),
]

_BRACE_LANGUAGES = {"javascript", "typescript", "go", "java", "rust"}

_LANGUAGE_PATTERNS: dict[str, list[tuple[re.Pattern, str]]] = {
    "javascript": _JS_TS_PATTERNS,
    "typescript": _JS_TS_PATTERNS,
    "go": _GO_PATTERNS,
    "java": _JAVA_PATTERNS,
    "ruby": _RUBY_PATTERNS,
    "rust": _RUST_PATTERNS,
}


def _regex_symbols(language: str, content: str) -> list[Symbol]:
    patterns = _LANGUAGE_PATTERNS.get(language)
    if not patterns:
        return []

    lines = content.splitlines()
    symbols: list[Symbol] = []
    for idx, line in enumerate(lines):
        for pattern, kind in patterns:
            match = pattern.match(line)
            if not match:
                continue
            start_line = idx + 1
            end_line = (
                _brace_block_end(lines, idx) if language in _BRACE_LANGUAGES else start_line
            )
            symbols.append(
                Symbol(name=match.group(1), kind=kind, start_line=start_line, end_line=end_line)
            )
            break
    return symbols


def extract_symbols(path: str, content: str, max_symbols: int) -> list[Symbol]:
    """Extract top-level (and one level of nested, for Python methods)
    symbols from one file's content. Never raises: malformed/unparsable
    content (this is untrusted PR content) yields an empty symbol list.
    """
    language = detect_language(path)
    if language == "python":
        symbols = _python_symbols(content)
    elif language:
        symbols = _regex_symbols(language, content)
    else:
        symbols = []
    return symbols[:max_symbols]
