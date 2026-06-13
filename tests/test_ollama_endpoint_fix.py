"""Regression tests for the Ollama endpoint configuration fix.

Three classes of assertion:

1. **Endpoint normalisation** — :func:`normalise_ollama_endpoint` always
   coerces the request URL to ``http://<host>:<port>/api/generate``
   regardless of how the user spelled the env var.
2. **Default Ollama model** — when ``MM_AI_LLM_MODEL`` is unset the
   adapter uses ``qwen2.5:7b`` so a fresh install hits a model that is
   reasonably likely to be available locally instead of the previous
   ``llama3.2`` default.
3. **Friendly user-facing error mapping** — :func:`talk_runner._friendly_error_text`
   translates adapter tokens (``timeout``, ``connection_failure: ...``,
   ``http_error: 404 ...``) into the spec-mandated strings shown in the
   response panel without exposing tracebacks.

No live LLM is contacted — every transport is a callable mock.
"""

from __future__ import annotations

import sys
import urllib.error
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.llm_adapter import (
    generate_llm_response,
    normalise_ollama_endpoint,
)
from src.llm_config import (
    DEFAULT_ENDPOINTS,
    DEFAULT_MODELS,
    ENV_BACKEND,
    ENV_ENDPOINT,
    ENV_MODEL,
    ENV_TIMEOUT,
    LLMConfig,
    load_config_from_env,
)
from src.llm_prompt_builder import build_llm_prompt
from src.llm_response_models import LLMResponse
from src.talk_runner import _friendly_error_text


# ---------------------------------------------------------------------------
# Endpoint normalisation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "given,expected",
    [
        # Already canonical -> passthrough.
        (
            "http://localhost:11434/api/generate",
            "http://localhost:11434/api/generate",
        ),
        # Bare host -> append the canonical path.
        ("http://localhost:11434", "http://localhost:11434/api/generate"),
        # Trailing slash -> append the canonical path.
        ("http://localhost:11434/", "http://localhost:11434/api/generate"),
        # OpenAI-compat path the user pasted by mistake -> rewrite.
        (
            "http://localhost:11434/v1/chat/completions",
            "http://localhost:11434/api/generate",
        ),
        # /api/chat (different body shape) -> rewrite.
        (
            "http://localhost:11434/api/chat",
            "http://localhost:11434/api/generate",
        ),
        # 127.0.0.1 + custom port.
        ("http://127.0.0.1:11434/foo", "http://127.0.0.1:11434/api/generate"),
        # https loopback.
        (
            "https://127.0.0.1:11434/",
            "https://127.0.0.1:11434/api/generate",
        ),
        # Query/fragment stripped.
        (
            "http://localhost:11434/api/generate?stream=true#hash",
            "http://localhost:11434/api/generate",
        ),
    ],
)
def test_normalise_ollama_endpoint(given, expected):
    assert normalise_ollama_endpoint(given) == expected


@pytest.mark.parametrize("garbage", ["", None, "not-a-url", "ftp://x/y"])
def test_normalise_ollama_endpoint_leaves_garbage_alone(garbage):
    # Garbage URLs are returned as-is so the existing ``endpoint_rejected``
    # security guard can still surface a clear error.
    assert normalise_ollama_endpoint(garbage) == garbage


def test_adapter_posts_to_normalised_endpoint_for_ollama():
    """Even if the config carries ``http://localhost:11434/``, the actual
    transport call must target the canonical Ollama generate path."""
    captured: dict = {}

    def fake_transport(url, body, timeout):
        captured["url"] = url
        captured["body"] = body
        return {"response": "OK reply."}

    cfg = LLMConfig("ollama", "qwen2.5:7b", "http://localhost:11434/", 5.0)
    payload = build_llm_prompt(
        "Why is NIFTY in news?",
        workspace_html=None,
        workspace_text="Latest Close:\n100\n",
        news_items=[],
        symbols=["NIFTY"],
    )
    resp = generate_llm_response(payload, cfg, transport=fake_transport)
    assert resp.ok
    assert captured["url"] == "http://localhost:11434/api/generate"
    assert captured["body"]["model"] == "qwen2.5:7b"
    assert captured["body"]["stream"] is False


def test_adapter_rewrites_v1_chat_completions_for_ollama_backend():
    captured: dict = {}

    def fake_transport(url, body, timeout):
        captured["url"] = url
        return {"response": "x"}

    cfg = LLMConfig(
        "ollama",
        "qwen2.5:7b",
        "http://localhost:11434/v1/chat/completions",
        5.0,
    )
    payload = build_llm_prompt(
        "anything", workspace_text="x", workspace_html=None,
        news_items=[], symbols=["RELIANCE"],
    )
    resp = generate_llm_response(payload, cfg, transport=fake_transport)
    assert resp.ok
    assert captured["url"] == "http://localhost:11434/api/generate"


# ---------------------------------------------------------------------------
# Default Ollama model
# ---------------------------------------------------------------------------


def test_default_ollama_model_is_qwen():
    assert DEFAULT_MODELS["ollama"] == "qwen2.5:7b"


def test_default_ollama_endpoint_is_api_generate():
    assert DEFAULT_ENDPOINTS["ollama"] == "http://localhost:11434/api/generate"


def test_env_config_defaults_to_qwen_when_model_unset(monkeypatch):
    for var in (ENV_BACKEND, ENV_MODEL, ENV_ENDPOINT, ENV_TIMEOUT):
        monkeypatch.delenv(var, raising=False)
    cfg = load_config_from_env()
    assert cfg.backend_type == "ollama"
    assert cfg.model_name == "qwen2.5:7b"
    assert cfg.endpoint_url == "http://localhost:11434/api/generate"


# ---------------------------------------------------------------------------
# 404 body extraction (Ollama returns ``{"error": "model ... not found"}``)
# ---------------------------------------------------------------------------


class _StubHTTPError(urllib.error.HTTPError):
    """HTTPError variant whose ``read()`` returns a pre-baked body."""

    def __init__(self, code: int, reason: str, body: bytes):
        super().__init__(
            "http://localhost:11434/api/generate", code, reason, {}, None  # type: ignore[arg-type]
        )
        self._body = body

    def read(self) -> bytes:  # type: ignore[override]
        return self._body


def test_404_with_ollama_error_body_surfaces_inner_detail():
    """The adapter must surface the JSON ``error`` field on a 404 so
    operators can see *which* model is missing."""

    def fake_transport(*_a, **_kw):
        body = b'{"error": "model \\"llama3.2\\" not found, try pulling it first"}'
        raise _StubHTTPError(404, "Not Found", body)

    cfg = LLMConfig(
        "ollama", "llama3.2", "http://localhost:11434/api/generate", 5.0
    )
    payload = build_llm_prompt(
        "What changed in SBICARD today?",
        workspace_text="x",
        workspace_html=None,
        news_items=[],
        symbols=["SBICARD"],
    )
    resp = generate_llm_response(payload, cfg, transport=fake_transport)
    assert not resp.ok
    assert resp.error is not None
    assert "http_error: 404 Not Found" in resp.error
    assert "model" in resp.error and "not found" in resp.error


def test_404_with_unparseable_body_does_not_crash():
    """If the body is not JSON we still attach a truncated text snippet
    rather than dropping the error."""

    def fake_transport(*_a, **_kw):
        raise _StubHTTPError(404, "Not Found", b"<html>page</html>")

    cfg = LLMConfig(
        "ollama", "qwen2.5:7b", "http://localhost:11434/api/generate", 5.0
    )
    payload = build_llm_prompt(
        "anything",
        workspace_text="x",
        workspace_html=None,
        news_items=[],
        symbols=["RELIANCE"],
    )
    resp = generate_llm_response(payload, cfg, transport=fake_transport)
    assert not resp.ok
    assert resp.error is not None
    assert "http_error: 404 Not Found" in resp.error


def test_existing_500_error_format_is_preserved():
    """The pre-existing ``http_error: 500`` token format must keep working
    so the existing :mod:`test_llm_adapter` suite stays green."""

    def fake_transport(*_a, **_kw):
        raise urllib.error.HTTPError(
            "http://localhost:11434/api/generate",
            500,
            "Internal Server Error",
            {},  # type: ignore[arg-type]
            None,
        )

    cfg = LLMConfig(
        "ollama", "qwen2.5:7b", "http://localhost:11434/api/generate", 5.0
    )
    payload = build_llm_prompt(
        "anything", workspace_text="x", workspace_html=None,
        news_items=[], symbols=["RELIANCE"],
    )
    resp = generate_llm_response(payload, cfg, transport=fake_transport)
    assert not resp.ok
    assert resp.error is not None
    assert "http_error: 500" in resp.error


# ---------------------------------------------------------------------------
# Friendly user-facing error mapping (talk_runner._friendly_error_text)
# ---------------------------------------------------------------------------


def _err_response(backend: str, error: str) -> LLMResponse:
    return LLMResponse(
        ok=False,
        backend=backend,
        model="qwen2.5:7b",
        endpoint="http://localhost:11434/api/generate",
        timestamp="25:05:26 15:00:00",
        response_text="",
        error=error,
        elapsed_ms=10,
        prompt_chars=0,
    )


def test_friendly_404_for_ollama_uses_spec_wording():
    resp = _err_response(
        "ollama",
        "http_error: 404 Not Found — model \"llama3.2\" not found",
    )
    assert _friendly_error_text(resp) == "Ollama endpoint returned 404."


def test_friendly_404_for_openai_compat_is_generic():
    resp = _err_response(
        "openai_compatible", "http_error: 404 Not Found"
    )
    assert _friendly_error_text(resp) == "Local model endpoint returned 404."


def test_friendly_timeout_message_without_seconds_is_generic():
    assert (
        _friendly_error_text(_err_response("ollama", "timeout"))
        == "Local model request timed out."
    )


def test_friendly_timeout_message_includes_configured_seconds():
    """When the adapter embedded ``timeout: 120`` the friendly text must
    surface the duration so the operator knows whether to bump the env
    var."""
    assert (
        _friendly_error_text(_err_response("ollama", "timeout: 120"))
        == "Local model request timed out after 120 seconds."
    )


def test_friendly_timeout_message_handles_float_seconds():
    assert (
        _friendly_error_text(_err_response("ollama", "timeout: 90.5"))
        == "Local model request timed out after 90.5 seconds."
    )


def test_friendly_timeout_message_strips_trailing_unit_in_token():
    assert (
        _friendly_error_text(_err_response("ollama", "timeout: 60s"))
        == "Local model request timed out after 60 seconds."
    )


def test_friendly_timeout_ignores_zero_token():
    assert (
        _friendly_error_text(_err_response("ollama", "timeout: 0"))
        == "Local model request timed out."
    )


def test_friendly_connection_refused_for_ollama():
    resp = _err_response("ollama", "connection_failure: Connection refused")
    assert (
        _friendly_error_text(resp)
        == "Unable to connect to local Ollama runtime."
    )


def test_friendly_connection_refused_for_openai_compat():
    resp = _err_response(
        "openai_compatible", "connection_failure: Connection refused"
    )
    assert _friendly_error_text(resp) == "Unable to connect to local local LLM runtime."


def test_friendly_endpoint_rejected():
    resp = _err_response("ollama", "endpoint_rejected: non_local_endpoint: 8.8.8.8")
    text = _friendly_error_text(resp)
    assert "Local LLM endpoint rejected" in text
    assert "MM_AI_LLM_ENDPOINT" in text


def test_friendly_5xx_is_generic():
    resp = _err_response("ollama", "http_error: 503 Service Unavailable")
    text = _friendly_error_text(resp)
    assert "server error" in text.lower()


def test_friendly_unknown_token_is_default_message():
    resp = _err_response("ollama", "something_unforeseen")
    assert _friendly_error_text(resp) == "Market response unavailable."


def test_friendly_error_does_not_expose_stack_traces():
    """A traceback-like adapter token must not leak verbatim to the panel."""
    resp = _err_response(
        "ollama",
        "unexpected_error: TypeError: Traceback (most recent call last):\n"
        "  File \"x.py\", line 1, in <module>\n    raise TypeError('boom')",
    )
    out = _friendly_error_text(resp)
    assert "Traceback" not in out
    assert "File \"x.py\"" not in out
    assert "boom" not in out
