import httpx
import pytest

from app.ai.model import GroqReviewModel, OllamaReviewModel, build_review_model
from app.config import Settings


def _model() -> OllamaReviewModel:
    return OllamaReviewModel(
        base_url="http://localhost:11434", model="qwen2.5-coder:7b",
        timeout_seconds=5, max_output_tokens=1024,
    )


def test_generate_returns_parsed_content_on_success(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_post(self, url, json):
        assert url == "/api/chat"
        payload = (
            '{"summary": "ok", "risk": "low", "confidence": 0.9, '
            '"decision": "approve", "issues": []}'
        )
        return httpx.Response(
            200,
            json={
                "message": {"content": payload},
                "prompt_eval_count": 120,
                "eval_count": 40,
            },
            request=httpx.Request("POST", "http://localhost:11434/api/chat"),
        )

    monkeypatch.setattr(httpx.Client, "post", fake_post)

    response = _model().generate(
        system="sys", messages=[{"role": "user", "content": "review this"}],
        response_schema={},
    )

    assert response.error is None
    assert response.content == {
        "summary": "ok", "risk": "low", "confidence": 0.9, "decision": "approve", "issues": [],
    }
    assert response.prompt_tokens == 120
    assert response.completion_tokens == 40


def test_generate_sets_error_on_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_post(self, url, json):
        raise httpx.TimeoutException("timed out")

    monkeypatch.setattr(httpx.Client, "post", fake_post)

    response = _model().generate(
        system="sys", messages=[{"role": "user", "content": "x"}], response_schema={}
    )

    assert response.content is None
    assert response.error == "ollama request timed out"


def test_generate_sets_error_on_connection_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_post(self, url, json):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx.Client, "post", fake_post)

    response = _model().generate(
        system="sys", messages=[{"role": "user", "content": "x"}], response_schema={}
    )

    assert response.content is None
    assert response.error is not None


def test_generate_sets_error_on_malformed_json_body(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_post(self, url, json):
        return httpx.Response(
            200,
            json={"message": {"content": "not json"}},
            request=httpx.Request("POST", "http://localhost:11434/api/chat"),
        )

    monkeypatch.setattr(httpx.Client, "post", fake_post)

    response = _model().generate(
        system="sys", messages=[{"role": "user", "content": "x"}], response_schema={}
    )

    assert response.content is None
    assert response.error == "model reply was not valid JSON"
    assert response.raw_text == "not json"


def test_build_review_model_returns_ollama_adapter_for_ollama_provider() -> None:
    model = build_review_model(Settings(ai_provider="ollama"))
    assert isinstance(model, OllamaReviewModel)


def test_build_review_model_returns_none_for_unknown_provider() -> None:
    assert build_review_model(Settings(ai_provider="totally-unknown")) is None


def test_groq_generate_uses_schema_prompt_and_local_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = GroqReviewModel(
        base_url="https://api.groq.com/openai/v1",
        api_key="test-key",
        model="openai/gpt-oss-20b",
        timeout_seconds=5,
        max_output_tokens=1024,
    )
    schema = {"type": "object", "properties": {"summary": {"type": "string"}}}

    def fake_post(self, url, json, headers):
        assert url == "/chat/completions"
        assert json["messages"][0]["role"] == "system"
        assert json["messages"][0]["content"].startswith("sys\n\n")
        assert "The JSON object you return MUST conform" in json["messages"][0]["content"]
        assert '"summary"' in json["messages"][0]["content"]
        assert "response_format" not in json
        assert json["reasoning_effort"] == "low"
        assert json["max_completion_tokens"] == 1024
        assert "max_tokens" not in json
        assert headers == {"Authorization": "Bearer test-key"}
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"summary":"ok"}'}}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 4},
            },
            request=httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions"),
        )

    monkeypatch.setattr(httpx.Client, "post", fake_post)

    response = model.generate(
        system="sys",
        messages=[{"role": "user", "content": "review this"}],
        response_schema=schema,
    )

    assert response.error is None
    assert response.content == {"summary": "ok"}
    assert response.prompt_tokens == 12
    assert response.completion_tokens == 4
