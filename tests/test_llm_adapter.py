"""Tests for the MM.AI local-LLM adapter.

Covers:
- Local-endpoint guard (loopback / private / public / bad scheme).
- Config loading from env (defaults, overrides, unsupported backend).
- Successful Ollama call (request body, response extraction).
- Successful OpenAI-compatible call (messages shape, choices extraction).
- Every failure mode: connection failure, timeout, malformed JSON, missing
  fields, public endpoint, invalid payload, unexpected exception.
- Response-text verbatim preservation (no trimming, no normalisation).
- ``probe_endpoint`` against a known-dead port.

All tests inject a fake ``transport`` — no test touches the real network.
"""

from __future__ import annotations

import json
import socket
import sys
import urllib.error
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.llm_adapter import (
    _is_local_endpoint,
    generate_llm_response,
    probe_endpoint,
)
from src.llm_config import (
    ENV_BACKEND,
    ENV_ENDPOINT,
    ENV_MODEL,
    ENV_TIMEOUT,
    LLMConfig,
    SUPPORTED_BACKENDS,
    load_config_from_env,
)
from src.llm_models import LLMPromptPayload
from src.llm_prompt_builder import build_llm_prompt
from src.llm_response_models import LLMResponse


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _sample_payload(
    question: str = "What changed in RELIANCE today?",
) -> LLMPromptPayload:
    return build_llm_prompt(
        question,
        workspace_html=None,
        workspace_text="Latest Close: 100\nClose Delta: 1.0",
        news_items=[],
        symbols=["RELIANCE"],
    )


def _ollama_cfg(
    endpoint: str = "http://localhost:11434/api/generate",
    timeout: float = 5.0,
) -> LLMConfig:
    return LLMConfig("ollama", "llama3.2", endpoint, timeout)


def _openai_cfg(
    endpoint: str = "http://localhost:8000/v1/chat/completions",
    timeout: float = 5.0,
) -> LLMConfig:
    return LLMConfig("openai_compatible", "local-model", endpoint, timeout)


# ---------------------------------------------------------------------------
# Local-endpoint guard
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:11434/api/generate",
        "http://127.0.0.1:8000/v1/chat/completions",
        "http://0.0.0.0:11434/api/generate",
        "http://[::1]:11434/api/generate",
        "http://192.168.1.10:11434/api/generate",
        "http://10.0.0.5:11434/api/generate",
        "http://172.16.5.5:11434/api/generate",
    ],
)
def test_local_endpoint_accepted(url):
    ok, reason = _is_local_endpoint(url)
    assert ok, f"expected accepted: {url} (reason={reason})"


@pytest.mark.parametrize(
    "url,fragment",
    [
        ("http://8.8.8.8/v1/chat/completions", "non_local_endpoint"),
        ("https://1.1.1.1/v1/chat/completions", "non_local_endpoint"),
        ("ftp://localhost/x", "unsupported_scheme"),
        ("not-a-url", "endpoint_missing_scheme"),
        ("http:///nohost", "endpoint_missing_host"),
    ],
)
def test_local_endpoint_rejected(url, fragment):
    ok, reason = _is_local_endpoint(url)
    assert not ok
    assert fragment in reason


def test_public_endpoint_blocked_before_any_transport_call():
    cfg = LLMConfig(
        "openai_compatible", "x", "http://8.8.8.8/v1/chat/completions", 5.0
    )

    def must_not_call(*_a, **_kw):
        raise AssertionError("transport must not be called for public endpoint")

    resp = generate_llm_response(_sample_payload(), cfg, transport=must_not_call)
    assert not resp.ok
    assert resp.error and "endpoint_rejected" in resp.error
    assert resp.response_text == ""


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------


def _clear_env(monkeypatch):
    for var in (ENV_BACKEND, ENV_MODEL, ENV_ENDPOINT, ENV_TIMEOUT):
        monkeypatch.delenv(var, raising=False)


def test_defaults_when_no_env(monkeypatch):
    _clear_env(monkeypatch)
    cfg = load_config_from_env()
    assert cfg.backend_type == "ollama"
    assert "11434" in cfg.endpoint_url
    assert cfg.model_name
    # Local-LLM default timeout raised so CPU-only Ollama runs have headroom.
    assert cfg.timeout_seconds == 120.0


def test_openrouter_api_key_selects_openrouter_backend_by_default(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    cfg = load_config_from_env()
    assert cfg.backend_type == "openrouter"
    assert cfg.endpoint_url == "https://openrouter.ai/api/v1/chat/completions"
    assert cfg.model_name == "openai/gpt-4o-mini"
    assert cfg.api_key == "test-key"


def test_openrouter_model_env_is_used(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv(ENV_BACKEND, "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("OPENROUTER_MODEL", "anthropic/claude-3.5-sonnet")
    cfg = load_config_from_env()
    assert cfg.backend_type == "openrouter"
    assert cfg.model_name == "anthropic/claude-3.5-sonnet"


def test_env_overrides(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv(ENV_BACKEND, "openai_compatible")
    monkeypatch.setenv(ENV_MODEL, "mymodel")
    monkeypatch.setenv(ENV_ENDPOINT, "http://127.0.0.1:9000/v1/chat/completions")
    monkeypatch.setenv(ENV_TIMEOUT, "30")
    cfg = load_config_from_env()
    assert cfg.backend_type == "openai_compatible"
    assert cfg.model_name == "mymodel"
    assert "9000" in cfg.endpoint_url
    assert cfg.timeout_seconds == 30.0


def test_unsupported_backend_raises(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv(ENV_BACKEND, "azure_openai")
    with pytest.raises(ValueError):
        load_config_from_env()


def test_invalid_timeout_falls_back_to_default(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv(ENV_TIMEOUT, "not-a-number")
    cfg = load_config_from_env()
    assert cfg.timeout_seconds == 120.0


def test_timeout_clamped(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv(ENV_TIMEOUT, "100000")
    cfg = load_config_from_env()
    assert cfg.timeout_seconds == 600.0
    monkeypatch.setenv(ENV_TIMEOUT, "0.1")
    cfg2 = load_config_from_env()
    assert cfg2.timeout_seconds == 1.0


# ---------------------------------------------------------------------------
# Ollama success path
# ---------------------------------------------------------------------------


def test_ollama_request_shape_and_response_extraction():
    payload = _sample_payload()
    cfg = _ollama_cfg()
    captured: dict = {}

    def fake_transport(url, body, timeout):
        captured["url"] = url
        captured["body"] = body
        captured["timeout"] = timeout
        return {
            "model": cfg.model_name,
            "response": "OK plain text response.",
            "done": True,
        }

    resp = generate_llm_response(payload, cfg, transport=fake_transport)

    assert resp.ok
    assert resp.backend == "ollama"
    assert resp.model == cfg.model_name
    assert resp.endpoint == cfg.endpoint_url
    assert resp.response_text == "OK plain text response."
    assert resp.error is None
    assert resp.prompt_chars == len(payload.prompt_text)
    assert resp.elapsed_ms >= 0
    # Request body must carry exactly the documented fields.
    assert captured["url"] == cfg.endpoint_url
    assert captured["timeout"] == cfg.timeout_seconds
    assert captured["body"] == {
        "model": cfg.model_name,
        "prompt": payload.prompt_text,
        "stream": False,
    }


# ---------------------------------------------------------------------------
# OpenAI-compatible success path
# ---------------------------------------------------------------------------


def test_openai_compat_request_shape_and_choice_extraction():
    payload = _sample_payload()
    cfg = _openai_cfg()
    captured: dict = {}

    def fake_transport(url, body, timeout):
        captured["url"] = url
        captured["body"] = body
        return {
            "choices": [
                {"message": {"role": "assistant", "content": "answer text"}}
            ]
        }

    resp = generate_llm_response(payload, cfg, transport=fake_transport)

    assert resp.ok
    assert resp.backend == "openai_compatible"
    assert resp.response_text == "answer text"
    assert captured["url"] == cfg.endpoint_url
    assert captured["body"] == {
        "model": cfg.model_name,
        "messages": [{"role": "user", "content": payload.prompt_text}],
        "stream": False,
    }


def test_openrouter_request_shape_with_injected_transport():
    payload = _sample_payload()
    cfg = LLMConfig(
        "openrouter",
        "openai/gpt-4o-mini",
        "https://openrouter.ai/api/v1/chat/completions",
        30.0,
        "test-key",
    )
    captured: dict = {}

    def fake_transport(url, body, timeout):
        captured["url"] = url
        captured["body"] = body
        captured["timeout"] = timeout
        return {"choices": [{"message": {"content": "openrouter answer"}}]}

    resp = generate_llm_response(payload, cfg, transport=fake_transport)

    assert resp.ok
    assert resp.backend == "openrouter"
    assert resp.response_text == "openrouter answer"
    assert captured["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert captured["body"] == {
        "model": "openai/gpt-4o-mini",
        "messages": [{"role": "user", "content": payload.prompt_text}],
        "stream": False,
    }


# ---------------------------------------------------------------------------
# Error handling — every failure mode must yield a deterministic LLMResponse
# ---------------------------------------------------------------------------


def test_timeout_is_reported_as_timeout():
    cfg = _ollama_cfg()

    def slow(*_a, **_kw):
        raise socket.timeout("timed out")

    resp = generate_llm_response(_sample_payload(), cfg, transport=slow)
    assert not resp.ok
    # Adapter embeds the configured timeout in the token so the response
    # panel can show "...after <N> seconds." Both the legacy "timeout"
    # prefix and the new integer suffix are guaranteed.
    assert resp.error is not None
    assert resp.error.startswith("timeout")
    assert resp.error == "timeout: 5"  # _ollama_cfg() defaults to 5.0s
    assert resp.response_text == ""


def test_connection_refused_is_reported():
    cfg = _ollama_cfg("http://127.0.0.1:1/api/generate")

    def dead(*_a, **_kw):
        raise urllib.error.URLError("Connection refused")

    resp = generate_llm_response(_sample_payload(), cfg, transport=dead)
    assert not resp.ok
    assert resp.error and resp.error.startswith("connection_failure")


def test_http_error_is_reported():
    cfg = _ollama_cfg()

    def http_500(*_a, **_kw):
        raise urllib.error.HTTPError(
            cfg.endpoint_url, 500, "Internal Server Error", {}, None  # type: ignore[arg-type]
        )

    resp = generate_llm_response(_sample_payload(), cfg, transport=http_500)
    assert not resp.ok
    assert resp.error and "http_error: 500" in resp.error


def test_invalid_json_is_reported():
    cfg = _ollama_cfg()

    def bad_json(*_a, **_kw):
        raise json.JSONDecodeError("expected value", "doc", 0)

    resp = generate_llm_response(_sample_payload(), cfg, transport=bad_json)
    assert not resp.ok
    assert resp.error and resp.error.startswith("invalid_json")


def test_malformed_ollama_response_missing_field():
    cfg = _ollama_cfg()

    def malformed(*_a, **_kw):
        return {"done": True}  # no "response"

    resp = generate_llm_response(_sample_payload(), cfg, transport=malformed)
    assert not resp.ok
    assert resp.error and "missing_response_field" in resp.error


def test_malformed_ollama_response_wrong_type():
    cfg = _ollama_cfg()

    def malformed(*_a, **_kw):
        return ["not", "a", "dict"]

    resp = generate_llm_response(_sample_payload(), cfg, transport=malformed)
    assert not resp.ok
    assert resp.error and "unexpected_response_type" in resp.error


def test_malformed_openai_response_no_choices():
    cfg = _openai_cfg()

    def malformed(*_a, **_kw):
        return {"choices": []}

    resp = generate_llm_response(_sample_payload(), cfg, transport=malformed)
    assert not resp.ok
    assert resp.error and "missing_choices" in resp.error


def test_malformed_openai_response_missing_message_content():
    cfg = _openai_cfg()

    def malformed(*_a, **_kw):
        return {"choices": [{"message": {"role": "assistant"}}]}

    resp = generate_llm_response(_sample_payload(), cfg, transport=malformed)
    assert not resp.ok
    assert resp.error and "missing_content" in resp.error


def test_invalid_payload_rejected():
    cfg = _ollama_cfg()
    resp = generate_llm_response("not a payload", cfg)  # type: ignore[arg-type]
    assert not resp.ok
    assert resp.error and "invalid_payload" in resp.error


def test_unknown_runtime_exception_is_swallowed_as_unexpected_error():
    cfg = _ollama_cfg()

    def explode(*_a, **_kw):
        raise RuntimeError("kaboom")

    resp = generate_llm_response(_sample_payload(), cfg, transport=explode)
    assert not resp.ok
    assert resp.error and "unexpected_error" in resp.error and "kaboom" in resp.error


# ---------------------------------------------------------------------------
# Response preservation contract
# ---------------------------------------------------------------------------


def test_response_text_is_preserved_verbatim():
    payload = _sample_payload()
    cfg = _ollama_cfg()
    verbatim = "Line 1\n  Line 2\tTabbed\n\nUnicode: ñ © 中文 🌐"

    def fake_transport(*_a, **_kw):
        return {"response": verbatim}

    resp = generate_llm_response(payload, cfg, transport=fake_transport)
    assert resp.ok
    assert resp.response_text == verbatim  # NO trimming, NO normalisation


def test_adapter_does_not_post_process_or_inject():
    """The adapter must not append any extra text to the model's reply."""
    cfg = _ollama_cfg()

    def fake_transport(*_a, **_kw):
        return {"response": "raw"}

    resp = generate_llm_response(_sample_payload(), cfg, transport=fake_transport)
    assert resp.response_text == "raw"


# ---------------------------------------------------------------------------
# probe_endpoint
# ---------------------------------------------------------------------------


def test_probe_endpoint_reports_unreachable():
    cfg = _ollama_cfg("http://127.0.0.1:1/api/generate")
    result = probe_endpoint(cfg, timeout=0.5)
    assert result["alive"] is False
    assert result["error"]


def test_probe_endpoint_rejects_non_local():
    cfg = LLMConfig(
        "ollama", "llama3.2", "http://8.8.8.8:80/api/generate", 1.0
    )
    result = probe_endpoint(cfg, timeout=0.5)
    assert result["alive"] is False
    assert result["error"] and "endpoint_rejected" in result["error"]


# ---------------------------------------------------------------------------
# Security: payload contents never leak outside prompt_text
# ---------------------------------------------------------------------------


def test_adapter_sends_only_prompt_text_for_ollama():
    payload = _sample_payload()
    cfg = _ollama_cfg()
    captured: dict = {}

    def fake_transport(url, body, timeout):
        captured["body"] = body
        return {"response": "x"}

    generate_llm_response(payload, cfg, transport=fake_transport)
    assert set(captured["body"].keys()) == {"model", "prompt", "stream"}


def test_adapter_sends_only_messages_for_openai_compat():
    payload = _sample_payload()
    cfg = _openai_cfg()
    captured: dict = {}

    def fake_transport(url, body, timeout):
        captured["body"] = body
        return {"choices": [{"message": {"content": "x"}}]}

    generate_llm_response(payload, cfg, transport=fake_transport)
    assert set(captured["body"].keys()) == {"model", "messages", "stream"}
    msgs = captured["body"]["messages"]
    assert len(msgs) == 1
    assert set(msgs[0].keys()) == {"role", "content"}


def test_response_is_immutable_and_has_dict_repr():
    cfg = _ollama_cfg()

    def fake_transport(*_a, **_kw):
        return {"response": "x"}

    resp = generate_llm_response(_sample_payload(), cfg, transport=fake_transport)
    with pytest.raises(Exception):
        resp.response_text = "mutated"  # type: ignore[misc]
    d = resp.as_dict()
    assert set(d.keys()) == {
        "ok",
        "backend",
        "model",
        "endpoint",
        "timestamp",
        "response_text",
        "error",
        "elapsed_ms",
        "prompt_chars",
    }
