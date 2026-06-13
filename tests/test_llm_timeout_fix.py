"""Regression tests for the local-LLM timeout configuration fix.

Three concerns:

1. Default timeout — ``DEFAULT_TIMEOUT_SECONDS`` is now ``120.0`` (was
   ``60.0``). A fresh install with no env vars set must report the new
   default value.
2. Environment override — ``MM_AI_LLM_TIMEOUT_SECONDS`` is honoured for
   valid positive numbers (incl. floats), silently falls back to the
   default for unparseable / blank / non-numeric strings, and is
   clamped to ``[MIN_TIMEOUT_SECONDS, MAX_TIMEOUT_SECONDS]``.
3. Adapter timeout token + friendly wording — the adapter embeds the
   configured duration in its error token (``timeout: <N>``) and the
   Talk runner surfaces it as ``"Local model request timed out after
   <N> seconds."`` so an operator can see whether to raise the env
   var. Stack traces never leak.
"""

from __future__ import annotations

import socket
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.llm_adapter import generate_llm_response
from src.llm_config import (
    DEFAULT_TIMEOUT_SECONDS,
    ENV_BACKEND,
    ENV_ENDPOINT,
    ENV_MODEL,
    ENV_TIMEOUT,
    LLMConfig,
    MAX_TIMEOUT_SECONDS,
    MIN_TIMEOUT_SECONDS,
    load_config_from_env,
)
from src.llm_prompt_builder import build_llm_prompt
from src.llm_response_models import LLMResponse
from src.talk_runner import _extract_timeout_seconds, _friendly_error_text


def _clear_env(monkeypatch):
    for var in (ENV_BACKEND, ENV_MODEL, ENV_ENDPOINT, ENV_TIMEOUT):
        monkeypatch.delenv(var, raising=False)


# ---------------------------------------------------------------------------
# 1. Default timeout
# ---------------------------------------------------------------------------


def test_default_timeout_constant_is_120():
    assert DEFAULT_TIMEOUT_SECONDS == 120.0


def test_load_config_default_timeout_is_120(monkeypatch):
    _clear_env(monkeypatch)
    cfg = load_config_from_env()
    assert cfg.timeout_seconds == 120.0


# ---------------------------------------------------------------------------
# 2. Env override
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("120", 120.0),
        ("180", 180.0),
        ("30", 30.0),
        ("60.5", 60.5),
        ("  240  ", 240.0),
    ],
)
def test_valid_positive_env_overrides(monkeypatch, raw, expected):
    _clear_env(monkeypatch)
    monkeypatch.setenv(ENV_TIMEOUT, raw)
    cfg = load_config_from_env()
    assert cfg.timeout_seconds == expected


@pytest.mark.parametrize("raw", ["abc", "", "  ", "not-a-number", "12abc"])
def test_invalid_env_falls_back_to_120(monkeypatch, raw):
    _clear_env(monkeypatch)
    monkeypatch.setenv(ENV_TIMEOUT, raw)
    cfg = load_config_from_env()
    assert cfg.timeout_seconds == DEFAULT_TIMEOUT_SECONDS == 120.0


def test_env_override_does_not_crash_for_garbage(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv(ENV_TIMEOUT, "abc")
    # Must not raise even though the value is unparseable.
    cfg = load_config_from_env()
    assert cfg.backend_type == "ollama"


def test_env_value_above_cap_is_clamped(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv(ENV_TIMEOUT, "100000")
    cfg = load_config_from_env()
    assert cfg.timeout_seconds == MAX_TIMEOUT_SECONDS


def test_env_value_below_floor_is_clamped(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv(ENV_TIMEOUT, "0.0001")
    cfg = load_config_from_env()
    assert cfg.timeout_seconds == MIN_TIMEOUT_SECONDS


def test_env_value_negative_is_clamped_to_min(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv(ENV_TIMEOUT, "-30")
    cfg = load_config_from_env()
    assert cfg.timeout_seconds == MIN_TIMEOUT_SECONDS


# ---------------------------------------------------------------------------
# 3. Adapter timeout token carries the configured seconds
# ---------------------------------------------------------------------------


def _payload():
    return build_llm_prompt(
        "What changed in RELIANCE today?",
        workspace_html=None,
        workspace_text="Latest Close: 100",
        news_items=[],
        symbols=["RELIANCE"],
    )


def test_adapter_timeout_token_carries_configured_seconds():
    cfg = LLMConfig(
        "ollama", "qwen2.5:7b", "http://127.0.0.1:11434/api/generate", 120.0
    )

    def slow(*_a, **_kw):
        raise socket.timeout("timed out")

    resp = generate_llm_response(_payload(), cfg, transport=slow)
    assert not resp.ok
    assert resp.error == "timeout: 120"


def test_adapter_timeout_token_rounds_floats_for_display():
    cfg = LLMConfig(
        "ollama", "qwen2.5:7b", "http://127.0.0.1:11434/api/generate", 89.6
    )

    def slow(*_a, **_kw):
        raise socket.timeout("timed out")

    resp = generate_llm_response(_payload(), cfg, transport=slow)
    assert not resp.ok
    # Rounding to the nearest whole second keeps the panel readable.
    assert resp.error == "timeout: 90"


# ---------------------------------------------------------------------------
# 4. Friendly translator surfaces the seconds value
# ---------------------------------------------------------------------------


def _err_response(error: str) -> LLMResponse:
    return LLMResponse(
        ok=False,
        backend="ollama",
        model="qwen2.5:7b",
        endpoint="http://localhost:11434/api/generate",
        timestamp="25:05:26 17:00:00",
        response_text="",
        error=error,
        elapsed_ms=120_000,
        prompt_chars=0,
    )


@pytest.mark.parametrize(
    "token,expected",
    [
        ("timeout: 120", "120"),
        ("timeout: 180", "180"),
        ("timeout: 60s", "60"),
        ("timeout: 90.5", "90.5"),
        ("timeout: 0", None),  # zero treated as "no value"
        ("timeout", None),
        ("timeout:", None),
        ("timeout: abc", None),
    ],
)
def test_extract_timeout_seconds(token, expected):
    assert _extract_timeout_seconds(token) == expected


def test_friendly_text_for_120s_timeout():
    assert (
        _friendly_error_text(_err_response("timeout: 120"))
        == "Local model request timed out after 120 seconds."
    )


def test_friendly_text_for_default_180s_override():
    assert (
        _friendly_error_text(_err_response("timeout: 180"))
        == "Local model request timed out after 180 seconds."
    )


def test_friendly_text_falls_back_when_seconds_missing():
    assert (
        _friendly_error_text(_err_response("timeout"))
        == "Local model request timed out."
    )


def test_friendly_text_never_leaks_stack_traces():
    """Even when the adapter wraps an unknown exception, the panel must
    receive a one-line factual message — no tracebacks."""
    msg = (
        "unexpected_error: RuntimeError: Traceback (most recent call last):\n"
        "  File \"x.py\", line 1, in <module>\n    raise RuntimeError(\"boom\")"
    )
    out = _friendly_error_text(_err_response(msg))
    assert "Traceback" not in out
    assert "File \"x.py\"" not in out
    assert "boom" not in out
    assert "\n" not in out
