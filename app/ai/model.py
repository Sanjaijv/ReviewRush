import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from app.config import Settings

logger = logging.getLogger(__name__)


@dataclass
class ModelResponse:
    """Provider-neutral result of one call to a review model.

    `content` is the parsed JSON body (or None if the reply wasn't valid
    JSON). `raw_text` is always kept, even on error, so a repair turn has
    something concrete to reference. `error` distinguishes "the model call
    itself failed" from "the model replied but the reply was bad" - both are
    treated as failures by the caller, but the message differs.
    """

    content: dict[str, Any] | None
    raw_text: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: int
    error: str | None = None


class ReviewModel(Protocol):
    """Provider-neutral interface for one coding-LLM reviewer.

    `messages` is a multi-turn chat history so a repair request can append
    the prior (invalid) assistant reply plus a correction instruction,
    rather than the interface only supporting a single user turn.

    `response_schema` is the caller's target JSON Schema (e.g.
    `AIReviewOutput.model_json_schema()` for a review, or
    `FixSuggestion.model_json_schema()` for an auto-fix suggestion) - the
    caller decides the shape, never the provider. Every caller must pass one
    explicitly; there is deliberately no default, so a new call site can
    never silently inherit some other feature's schema.
    """

    def generate(
        self, *, system: str, messages: list[dict[str, str]], response_schema: dict[str, Any]
    ) -> ModelResponse: ...


class OllamaReviewModel:
    """Calls a local Ollama server's chat API with JSON-schema-constrained
    output. No API key: Ollama is assumed to be a locally/privately reachable
    server, never the public internet, so nothing secret needs to be sent or
    logged here.
    """

    def __init__(self, base_url: str, model: str, timeout_seconds: int, max_output_tokens: int):
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._max_output_tokens = max_output_tokens

    def generate(
        self, *, system: str, messages: list[dict[str, str]], response_schema: dict[str, Any]
    ) -> ModelResponse:
        started = time.monotonic()
        payload = {
            "model": self._model,
            "messages": [{"role": "system", "content": system}, *messages],
            "format": response_schema,
            "stream": False,
            "options": {"num_predict": self._max_output_tokens},
        }

        try:
            with httpx.Client(base_url=self._base_url, timeout=self._timeout_seconds) as client:
                response = client.post("/api/chat", json=payload)
                response.raise_for_status()
                body = response.json()
        except httpx.TimeoutException:
            return ModelResponse(
                content=None,
                raw_text="",
                prompt_tokens=0,
                completion_tokens=0,
                latency_ms=int((time.monotonic() - started) * 1000),
                error="ollama request timed out",
            )
        except httpx.HTTPError as exc:
            return ModelResponse(
                content=None,
                raw_text="",
                prompt_tokens=0,
                completion_tokens=0,
                latency_ms=int((time.monotonic() - started) * 1000),
                error=f"ollama request failed: {exc}",
            )

        latency_ms = int((time.monotonic() - started) * 1000)
        raw_text = ((body.get("message") or {}).get("content")) or ""
        prompt_tokens = int(body.get("prompt_eval_count") or 0)
        completion_tokens = int(body.get("eval_count") or 0)

        try:
            content = json.loads(raw_text)
        except (json.JSONDecodeError, ValueError):
            return ModelResponse(
                content=None,
                raw_text=raw_text,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                latency_ms=latency_ms,
                error="model reply was not valid JSON",
            )

        if not isinstance(content, dict):
            return ModelResponse(
                content=None,
                raw_text=raw_text,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                latency_ms=latency_ms,
                error="model reply was not a JSON object",
            )

        return ModelResponse(
            content=content,
            raw_text=raw_text,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            latency_ms=latency_ms,
        )


class GroqReviewModel:
    """Calls Groq's OpenAI-compatible chat completions API. Groq hosts
    open-weight models on custom inference hardware, so responses are
    dramatically faster than local CPU-only inference - useful when the
    reviewing host has no GPU. Requires an API key (free tier available at
    console.groq.com); unlike Ollama this is a public third-party service,
    so the diff/prompt content leaves the local network.
    """

    def __init__(
        self, base_url: str, api_key: str, model: str, timeout_seconds: int, max_output_tokens: int
    ):
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._max_output_tokens = max_output_tokens

    def generate(
        self, *, system: str, messages: list[dict[str, str]], response_schema: dict[str, Any]
    ) -> ModelResponse:
        started = time.monotonic()
        # Unlike Ollama's structural "format" json-schema constraint, Groq's
        # json_object mode only guarantees syntactically valid JSON - it has
        # no notion of the target field names, so the schema must be spelled
        # out in the prompt text itself for the model to follow it.
        schema_system = (
            f"{system}\n\nThe JSON object you return MUST conform to this JSON "
            f"Schema:\n{json.dumps(response_schema)}"
        )
        payload = {
            "model": self._model,
            "messages": [{"role": "system", "content": schema_system}, *messages],
            "response_format": {"type": "json_object"},
            "max_tokens": self._max_output_tokens,
        }
        headers = {"Authorization": f"Bearer {self._api_key}"}

        try:
            with httpx.Client(base_url=self._base_url, timeout=self._timeout_seconds) as client:
                response = client.post("/chat/completions", json=payload, headers=headers)
                response.raise_for_status()
                body = response.json()
        except httpx.TimeoutException:
            return ModelResponse(
                content=None,
                raw_text="",
                prompt_tokens=0,
                completion_tokens=0,
                latency_ms=int((time.monotonic() - started) * 1000),
                error="groq request timed out",
            )
        except httpx.HTTPError as exc:
            return ModelResponse(
                content=None,
                raw_text="",
                prompt_tokens=0,
                completion_tokens=0,
                latency_ms=int((time.monotonic() - started) * 1000),
                error=f"groq request failed: {exc}",
            )

        latency_ms = int((time.monotonic() - started) * 1000)
        choices = body.get("choices") or []
        raw_text = ((choices[0].get("message") or {}).get("content")) if choices else ""
        raw_text = raw_text or ""
        usage = body.get("usage") or {}
        prompt_tokens = int(usage.get("prompt_tokens") or 0)
        completion_tokens = int(usage.get("completion_tokens") or 0)

        try:
            content = json.loads(raw_text)
        except (json.JSONDecodeError, ValueError):
            return ModelResponse(
                content=None,
                raw_text=raw_text,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                latency_ms=latency_ms,
                error="model reply was not valid JSON",
            )

        if not isinstance(content, dict):
            return ModelResponse(
                content=None,
                raw_text=raw_text,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                latency_ms=latency_ms,
                error="model reply was not a JSON object",
            )

        return ModelResponse(
            content=content,
            raw_text=raw_text,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            latency_ms=latency_ms,
        )


def build_review_model(
    settings: Settings, *, provider: str | None = None, model_name: str | None = None
) -> ReviewModel | None:
    """Factory keyed on the effective provider/model. An unknown provider
    logs and returns None rather than raising - the caller must treat that
    the same as any other model failure (fail closed to human review).

    `provider`/`model_name` default to the global `settings.ai_provider` /
    `settings.ai_model` but can be overridden per call - this is how a
    Phase 17 `Organization.ai_provider_override` / `ai_model_override` (a
    customer-managed model setting) takes effect without introducing a
    second config system: it's still only the same single Ollama provider
    this release supports, just pointed at a different org-chosen model
    name. The Ollama base URL itself is not yet overridable per organization.
    """
    effective_provider = provider or settings.ai_provider
    effective_model = model_name or settings.ai_model
    if effective_provider == "ollama":
        return OllamaReviewModel(
            base_url=settings.ai_ollama_base_url,
            model=effective_model,
            timeout_seconds=settings.ai_request_timeout_seconds,
            max_output_tokens=settings.ai_max_output_tokens,
        )
    if effective_provider == "groq":
        if not settings.ai_groq_api_key:
            logger.error("groq provider configured without an API key")
            return None
        return GroqReviewModel(
            base_url=settings.ai_groq_base_url,
            api_key=settings.ai_groq_api_key,
            model=effective_model,
            timeout_seconds=settings.ai_request_timeout_seconds,
            max_output_tokens=settings.ai_max_output_tokens,
        )
    logger.error("unknown AI provider configured", extra={"provider": effective_provider})
    return None
