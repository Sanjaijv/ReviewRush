"""Reads repository guidance documents (AGENTS.md, CONTRIBUTING.md, etc.)
from a workspace checkout, bounded per-file and treated as untrusted data
by every downstream consumer (see `app/ai/prompt.py`'s system prompt).
"""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class GuidanceDoc:
    path: str
    content: str
    truncated: bool


def load_guidance_docs(
    root: Path, filenames: list[str], max_bytes_each: int
) -> list[GuidanceDoc]:
    docs: list[GuidanceDoc] = []
    for name in filenames:
        candidate = (root / name)
        try:
            resolved = candidate.resolve()
            if not str(resolved).startswith(str(root.resolve())):
                continue
            if not candidate.is_file():
                continue
            raw = candidate.read_bytes()
        except OSError:
            continue

        truncated = len(raw) > max_bytes_each
        content = raw[:max_bytes_each].decode("utf-8", errors="replace")
        docs.append(GuidanceDoc(path=name, content=content, truncated=truncated))
    return docs
