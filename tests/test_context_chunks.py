from pathlib import Path
from unittest.mock import MagicMock

from app.context.chunks import (
    reindex_changed_file_chunks,
    reindex_symbol_chunks,
)
from app.context.embeddings import EmbeddingResponse
from app.context.symbols import Symbol
from app.models import ChangedFile, RepoSymbolChunk


class _FakeEmbeddingProvider:
    def __init__(self, vector=None, error=None):
        self._vector = vector
        self._error = error
        self.calls: list[str] = []

    def embed(self, text: str) -> EmbeddingResponse:
        self.calls.append(text)
        return EmbeddingResponse(vector=self._vector, latency_ms=1, error=self._error)


def _db_with_no_existing_rows() -> MagicMock:
    db = MagicMock()
    db.query.return_value.filter_by.return_value.__iter__.return_value = iter([])
    return db


def test_reindex_symbol_chunks_upserts_row_with_relationships_and_embedding() -> None:
    db = _db_with_no_existing_rows()
    content_lines = ["def changed():", "    return helper()"]
    symbol = Symbol(name="changed", kind="function", start_line=1, end_line=2)
    provider = _FakeEmbeddingProvider(vector=[0.1, 0.2])

    reindex_symbol_chunks(
        db=db,
        repository_id=1,
        path="app.py",
        content_lines=content_lines,
        content_sha="sha1",
        symbols=[symbol],
        head_sha="headsha",
        embedding_provider=provider,
        embedding_model="nomic-embed-text",
    )

    db.add.assert_called_once()
    row: RepoSymbolChunk = db.add.call_args[0][0]
    assert row.path == "app.py"
    assert row.symbol == "changed"
    assert row.relationships == ["helper"]
    assert row.embedding == [0.1, 0.2]
    assert row.embedding_model == "nomic-embed-text"
    assert row.last_seen_commit_sha == "headsha"


def test_reindex_symbol_chunks_never_stores_chunk_text() -> None:
    db = _db_with_no_existing_rows()
    content_lines = ["def secret_impl():", "    return 'super-secret-literal'"]
    symbol = Symbol(name="secret_impl", kind="function", start_line=1, end_line=2)

    reindex_symbol_chunks(
        db=db,
        repository_id=1,
        path="app.py",
        content_lines=content_lines,
        content_sha="sha1",
        symbols=[symbol],
        head_sha="headsha",
        embedding_provider=None,
        embedding_model="",
    )

    row: RepoSymbolChunk = db.add.call_args[0][0]
    dumped = {c.key: getattr(row, c.key, None) for c in RepoSymbolChunk.__table__.columns}
    assert "super-secret-literal" not in str(dumped)


def test_reindex_symbol_chunks_skips_embedding_on_provider_failure() -> None:
    db = _db_with_no_existing_rows()
    symbol = Symbol(name="f", kind="function", start_line=1, end_line=1)
    provider = _FakeEmbeddingProvider(vector=None, error="boom")

    reindex_symbol_chunks(
        db=db,
        repository_id=1,
        path="app.py",
        content_lines=["def f(): pass"],
        content_sha="sha1",
        symbols=[symbol],
        head_sha="headsha",
        embedding_provider=provider,
        embedding_model="nomic-embed-text",
    )

    row: RepoSymbolChunk = db.add.call_args[0][0]
    assert row.embedding is None
    assert row.embedding_model is None


def test_reindex_symbol_chunks_deletes_stale_symbol_rows() -> None:
    stale_row = RepoSymbolChunk(
        repository_id=1, path="app.py", symbol="removed_fn",
        kind="function", start_line=1, end_line=1,
        content_sha="old", last_seen_commit_sha="old-sha",
    )
    db = MagicMock()
    db.query.return_value.filter_by.return_value.__iter__.return_value = iter([stale_row])

    reindex_symbol_chunks(
        db=db,
        repository_id=1,
        path="app.py",
        content_lines=["def kept(): pass"],
        content_sha="sha2",
        symbols=[Symbol(name="kept", kind="function", start_line=1, end_line=1)],
        head_sha="headsha",
        embedding_provider=None,
        embedding_model="",
    )

    db.delete.assert_called_once_with(stale_row)


def test_reindex_changed_file_chunks_deletes_chunks_for_removed_file() -> None:
    db = MagicMock()
    changed_file = ChangedFile(new_path=None, old_path="gone.py", status="removed")
    row = RepoSymbolChunk(
        repository_id=1, path="gone.py", symbol="f", kind="function",
        start_line=1, end_line=1, content_sha="x", last_seen_commit_sha="x",
    )
    db.query.return_value.filter_by.return_value.__iter__.return_value = iter([row])

    reindex_changed_file_chunks(
        db=db,
        repository_id=1,
        workspace_root=Path("/tmp/does-not-matter"),
        changed_files=[changed_file],
        head_sha="headsha",
        max_file_bytes=500_000,
        max_symbols_per_file=50,
        embedding_provider=None,
        embedding_model="",
    )

    db.query.return_value.filter_by.assert_called_with(repository_id=1, path="gone.py")
    db.delete.assert_called_once_with(row)


def test_reindex_changed_file_chunks_indexes_symbols_for_modified_file(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("def changed():\n    return 1\n")
    db = _db_with_no_existing_rows()
    changed_file = ChangedFile(new_path="app.py", old_path="app.py", status="modified")

    reindex_changed_file_chunks(
        db=db,
        repository_id=1,
        workspace_root=tmp_path,
        changed_files=[changed_file],
        head_sha="headsha",
        max_file_bytes=500_000,
        max_symbols_per_file=50,
        embedding_provider=None,
        embedding_model="",
    )

    db.add.assert_called_once()
    row: RepoSymbolChunk = db.add.call_args[0][0]
    assert row.symbol == "changed"
