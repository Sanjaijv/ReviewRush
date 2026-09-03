"""Provider-neutral embedding calls for semantic retrieval (Phase 11).

Mirrors `app/ai/model.py`'s provider pattern deliberately: same shape
(`EmbeddingResponse`/`EmbeddingProvider`/`build_embedding_provider`), same
"never raise, report failure on the response" contract, and the same
locally-hosted-only assumption for Ollama (no API key, never the public
internet). Embedding failures must never crash indexing - a caller that
can't get a vector for one chunk just skips semantic augmentation for it and
keeps the lexical/structural result, per the roadmap's documented degraded
mode.
"""

import logging
import time
from dataclasses import dataclass
from typing import Protocol

import httpx

from app.config import Settings

logger = logging.getLogger(__name__)


@dataclass
class EmbeddingResponse:
    vector: list[float] | None
    latency_ms: int
    error: str | None = None


class EmbeddingProvider(Protocol):
    def embed(self, text: str) -> EmbeddingResponse: ...


class OllamaEmbeddingProvider:
    """Calls a local Ollama server's embeddings API. No API key, same
    trust assumption as `OllamaReviewModel`: the server is private/local,
    never the public internet.
    """

    def __init__(self, base_url: str, model: str, timeout_seconds: int):
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout_seconds = timeout_seconds

    def embed(self, text: str) -> EmbeddingResponse:
        started = time.monotonic()
        try:
            with httpx.Client(base_url=self._base_url, timeout=self._timeout_seconds) as client:
                response = client.post(
                    "/api/embeddings", json={"model": self._model, "prompt": text}
                )
                response.raise_for_status()
                body = response.json()
        except httpx.TimeoutException:
            return EmbeddingResponse(
                vector=None,
                latency_ms=int((time.monotonic() - started) * 1000),
                error="ollama embeddings request timed out",
            )
        except httpx.HTTPError as exc:
            return EmbeddingResponse(
                vector=None,
                latency_ms=int((time.monotonic() - started) * 1000),
                error=f"ollama embeddings request failed: {exc}",
            )

        latency_ms = int((time.monotonic() - started) * 1000)
        vector = body.get("embedding")
        if not isinstance(vector, list) or not vector:
            return EmbeddingResponse(
                vector=None, latency_ms=latency_ms, error="ollama reply had no embedding"
            )
        return EmbeddingResponse(vector=[float(v) for v in vector], latency_ms=latency_ms)


def build_embedding_provider(settings: Settings) -> EmbeddingProvider | None:
    """Factory keyed on `settings.context_embeddings_provider`. Returns None
    when embeddings are disabled or the provider is unknown, so callers treat
    that identically to any other embedding failure: skip semantic
    augmentation, keep lexical/structural retrieval.
    """
    if not settings.context_embeddings_enabled:
        return None
    if settings.context_embeddings_provider == "ollama":
        return OllamaEmbeddingProvider(
            base_url=settings.ai_ollama_base_url,
            model=settings.context_embeddings_model,
            timeout_seconds=settings.context_embeddings_timeout_seconds,
        )
    logger.error(
        "unknown embeddings provider configured",
        extra={"provider": settings.context_embeddings_provider},
    )
    return None
