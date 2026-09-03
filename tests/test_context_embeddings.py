import httpx
import pytest

from app.config import Settings
from app.context.embeddings import OllamaEmbeddingProvider, build_embedding_provider


def _provider() -> OllamaEmbeddingProvider:
    return OllamaEmbeddingProvider(
        base_url="http://localhost:11434", model="nomic-embed-text", timeout_seconds=5
    )


def test_embed_returns_vector_on_success(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_post(self, url, json):
        assert url == "/api/embeddings"
        assert json == {"model": "nomic-embed-text", "prompt": "def f(): pass"}
        return httpx.Response(
            200,
            json={"embedding": [0.1, 0.2, 0.3]},
            request=httpx.Request("POST", "http://localhost:11434/api/embeddings"),
        )

    monkeypatch.setattr(httpx.Client, "post", fake_post)

    response = _provider().embed("def f(): pass")

    assert response.error is None
    assert response.vector == [0.1, 0.2, 0.3]


def test_embed_sets_error_on_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_post(self, url, json):
        raise httpx.TimeoutException("timed out")

    monkeypatch.setattr(httpx.Client, "post", fake_post)

    response = _provider().embed("text")

    assert response.vector is None
    assert response.error == "ollama embeddings request timed out"


def test_embed_sets_error_on_connection_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_post(self, url, json):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx.Client, "post", fake_post)

    response = _provider().embed("text")

    assert response.vector is None
    assert response.error is not None


def test_embed_sets_error_when_reply_has_no_embedding(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_post(self, url, json):
        return httpx.Response(
            200,
            json={},
            request=httpx.Request("POST", "http://localhost:11434/api/embeddings"),
        )

    monkeypatch.setattr(httpx.Client, "post", fake_post)

    response = _provider().embed("text")

    assert response.vector is None
    assert response.error == "ollama reply had no embedding"


def test_build_embedding_provider_returns_none_when_disabled() -> None:
    settings = Settings(context_embeddings_enabled=False)

    assert build_embedding_provider(settings) is None


def test_build_embedding_provider_returns_ollama_provider_when_enabled() -> None:
    settings = Settings(context_embeddings_enabled=True, context_embeddings_provider="ollama")

    provider = build_embedding_provider(settings)

    assert isinstance(provider, OllamaEmbeddingProvider)


def test_build_embedding_provider_returns_none_for_unknown_provider() -> None:
    settings = Settings(context_embeddings_enabled=True, context_embeddings_provider="bogus")

    assert build_embedding_provider(settings) is None
