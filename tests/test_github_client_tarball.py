from contextlib import contextmanager
from pathlib import Path

import pytest

from app.github.client import GitHubClient


class _FakeStreamResponse:
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks

    def raise_for_status(self) -> None:
        pass

    def iter_bytes(self):
        yield from self._chunks


def _client_with_stream(chunks: list[bytes]) -> GitHubClient:
    client = GitHubClient("test-token")

    @contextmanager
    def fake_stream(method, url, follow_redirects=True, timeout=None):
        yield _FakeStreamResponse(chunks)

    client._client.stream = fake_stream  # type: ignore[method-assign]
    return client


def test_download_tarball_writes_all_chunks(tmp_path: Path) -> None:
    client = _client_with_stream([b"abc", b"def"])
    dest = tmp_path / "out.tar.gz"

    client.download_tarball("acme", "widgets", "sha1", dest, max_bytes=1000)

    assert dest.read_bytes() == b"abcdef"


def test_download_tarball_rejects_oversized_archive(tmp_path: Path) -> None:
    client = _client_with_stream([b"x" * 10, b"y" * 10])
    dest = tmp_path / "out.tar.gz"

    with pytest.raises(ValueError):
        client.download_tarball("acme", "widgets", "sha1", dest, max_bytes=15)
