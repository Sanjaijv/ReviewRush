"""Symbol-chunk indexing for RAG retrieval (Phase 11): upserts one
`RepoSymbolChunk` row per symbol in a changed file, with lexically-detected
relationships (other symbols called/referenced within the chunk) and,
if embeddings are enabled, a semantic vector.

Runs immediately after `reindex_changed_files` (app/context/retrieval.py)
in the same "only re-index files this diff actually touched" pass, keyed on
the same per-file `content_sha`. Like `RepoFileIndex`, no chunk text is
persisted - only symbol metadata, lexical relationships, and an embedding
vector that cannot be turned back into source text.
"""

import hashlib
import logging
import re
from pathlib import Path
from typing import Any

from app.context.embeddings import EmbeddingProvider
from app.context.symbols import Symbol, detect_language, extract_symbols
from app.models import ChangedFile, RepoSymbolChunk

logger = logging.getLogger(__name__)

_CALL_PATTERN = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(")
_MAX_RELATIONSHIPS = 20


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_file(path: Path, max_bytes: int) -> str | None:
    try:
        if path.stat().st_size > max_bytes:
            return None
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _chunk_text(content_lines: list[str], symbol: Symbol) -> str:
    lo = max(1, symbol.start_line)
    hi = min(len(content_lines), symbol.end_line)
    return "\n".join(content_lines[lo - 1 : hi])


def _relationships_in_chunk(chunk_text: str, own_name: str) -> list[str]:
    names: list[str] = []
    seen = {own_name}
    for match in _CALL_PATTERN.finditer(chunk_text):
        name = match.group(1)
        if name in seen:
            continue
        seen.add(name)
        names.append(name)
        if len(names) >= _MAX_RELATIONSHIPS:
            break
    return names


def reindex_symbol_chunks(
    db: Any,
    repository_id: int,
    path: str,
    content_lines: list[str],
    content_sha: str,
    symbols: list[Symbol],
    head_sha: str,
    embedding_provider: EmbeddingProvider | None,
    embedding_model: str,
) -> None:
    """Upsert one `RepoSymbolChunk` per symbol in `symbols` (already the
    full symbol set for `path`, matching `RepoFileIndex.symbols`). Symbols
    no longer present in the file are deleted so the chunk table never
    drifts from the current head_sha's symbol set for this path.

    Never raises: an embedding failure for one symbol just leaves that
    row's `embedding` null (skip semantic augmentation for it) rather than
    aborting the rest of the file's chunks.
    """
    current_names = {symbol.name for symbol in symbols}
    existing_rows = {
        row.symbol: row
        for row in db.query(RepoSymbolChunk).filter_by(repository_id=repository_id, path=path)
    }

    for stale_name, row in existing_rows.items():
        if stale_name not in current_names:
            db.delete(row)

    for symbol in symbols:
        chunk_text = _chunk_text(content_lines, symbol)
        relationships = _relationships_in_chunk(chunk_text, symbol.name)

        vector: list[float] | None = None
        model_used: str | None = None
        if embedding_provider is not None:
            try:
                response = embedding_provider.embed(chunk_text)
            except Exception:  # a provider bug must never abort indexing
                logger.exception(
                    "embedding provider raised unexpectedly",
                    extra={"repository_id": repository_id, "path": path, "symbol": symbol.name},
                )
            else:
                if response.error is not None:
                    logger.warning(
                        "embedding failed, chunk kept lexical-only",
                        extra={
                            "repository_id": repository_id,
                            "path": path,
                            "symbol": symbol.name,
                            "error": response.error,
                        },
                    )
                else:
                    vector = response.vector
                    model_used = embedding_model

        row = existing_rows.get(symbol.name)
        content_changed = row is None or row.content_sha != content_sha
        if row is None:
            row = RepoSymbolChunk(repository_id=repository_id, path=path, symbol=symbol.name)
            db.add(row)

        row.kind = symbol.kind
        row.start_line = symbol.start_line
        row.end_line = symbol.end_line
        row.content_sha = content_sha
        row.relationships = relationships
        row.last_seen_commit_sha = head_sha
        if vector is not None:
            row.embedding = vector
            row.embedding_model = model_used
        elif content_changed:
            # The chunk's text actually changed and embedding it failed -
            # serving the old vector would silently mix stale semantics
            # into new content, so drop it rather than keep a mismatch.
            row.embedding = None
            row.embedding_model = None
        # else: content is unchanged from the last successful index (e.g. a
        # retry) - keep whatever vector is already there rather than
        # blowing away a good embedding over a transient provider failure.


def reindex_changed_file_chunks(
    db: Any,
    repository_id: int,
    workspace_root: Path,
    changed_files: list[ChangedFile],
    head_sha: str,
    max_file_bytes: int,
    max_symbols_per_file: int,
    embedding_provider: EmbeddingProvider | None,
    embedding_model: str,
) -> None:
    """Drive `reindex_symbol_chunks` for exactly the files this diff
    touched, mirroring `reindex_changed_files` (app/context/retrieval.py)
    file-selection behavior 1:1 so the chunk table and `RepoFileIndex` stay
    in step. A removed file's chunks are deleted outright.
    """
    for changed_file in changed_files:
        if changed_file.status == "removed":
            old_path = changed_file.old_path
            if old_path:
                for row in db.query(RepoSymbolChunk).filter_by(
                    repository_id=repository_id, path=old_path
                ):
                    db.delete(row)
            continue

        path = changed_file.new_path or changed_file.old_path
        if not path:
            continue

        content = _read_file(workspace_root / path, max_file_bytes)
        if content is None:
            continue

        content_sha = _sha256_hex(content.encode("utf-8", errors="replace"))
        symbols = extract_symbols(path, content, max_symbols_per_file)
        if not detect_language(path):
            continue

        reindex_symbol_chunks(
            db=db,
            repository_id=repository_id,
            path=path,
            content_lines=content.splitlines(),
            content_sha=content_sha,
            symbols=symbols,
            head_sha=head_sha,
            embedding_provider=embedding_provider,
            embedding_model=embedding_model,
        )
