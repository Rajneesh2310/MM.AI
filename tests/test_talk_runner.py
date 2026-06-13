"""Tests for the TalkRunner controller.

Covers the deterministic plumbing between the Talk to Market UI and the
safe prompt builder + local-LLM adapter:

- empty question        -> "Enter a market question." (error kind)
- no workspace loaded   -> "No workspace loaded. Enter a symbol or ask
                            about a symbol directly." (fallback kind)
- workspace loaded + transport mocked -> verbatim response text,
                                        kind="ok"
- adapter returns ok=False -> the error string is surfaced verbatim
- transport raises (timeout, conn refused, malformed) -> error surfaced
- prompt builder rejects the input -> 'prompt_rejected: ...' error
- payload contents -> only sanitised workspace_text + question + news +
                      symbols are sent. No HTML, no parquet paths.
- ask() async path also fires started + finished_ok signals.
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

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication

from src.llm_config import LLMConfig
from src.llm_models import LLMPromptPayload
from src.news_models import NewsItem, NewsResult
from src.talk_runner import (
    EMPTY_QUESTION_MESSAGE,
    NO_WORKSPACE_MESSAGE,
    TalkRunner,
)


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication(sys.argv)
    yield app


def _cfg() -> LLMConfig:
    return LLMConfig(
        "ollama", "mock-model", "http://127.0.0.1:11434/api/generate", 5.0
    )


SAMPLE_WORKSPACE_TEXT = (
    "[25:05:26 14:00:00]\n\nSYMBOL: RELIANCE\n\nCASH\n\n"
    "Latest Close:\n1359.7\n\nClose Delta:\n37.0\n"
)


def _sample_news() -> list[NewsResult]:
    return [
        NewsResult(
            symbol="RELIANCE",
            timestamp="25:05:26 14:00:01",
            count=1,
            items=[
                NewsItem(
                    headline="RELIANCE quarterly results published",
                    source="Wire24",
                    url="https://news.example/reliance-q",
                    timestamp="25:05:26 14:00:01",
                )
            ],
        )
    ]


# ---------------------------------------------------------------------------
# Empty / no-workspace fallbacks
# ---------------------------------------------------------------------------


def test_empty_question_returns_error_message():
    runner = TalkRunner(config=_cfg())
    kind, text, ts = runner.ask_sync("")
    assert kind == "error"
    assert text == EMPTY_QUESTION_MESSAGE
    assert ts  # non-empty timestamp


def test_whitespace_question_treated_as_empty():
    runner = TalkRunner(config=_cfg())
    kind, text, _ts = runner.ask_sync("   \n\t  ")
    assert kind == "error"
    assert text == EMPTY_QUESTION_MESSAGE


def test_no_workspace_loaded_returns_fallback_message():
    runner = TalkRunner(config=_cfg())
    kind, text, _ts = runner.ask_sync("What changed in RELIANCE today?")
    assert kind == "fallback"
    assert text == NO_WORKSPACE_MESSAGE


def test_workspace_text_alone_counts_as_loaded():
    runner = TalkRunner(config=_cfg(), transport=lambda *_a, **_kw: {"response": "x"})
    runner.set_workspace(SAMPLE_WORKSPACE_TEXT, None, [], [])
    kind, text, _ts = runner.ask_sync("Show INFY activity.")
    assert kind == "ok"
    assert text == "x"


def test_symbols_alone_count_as_loaded():
    runner = TalkRunner(config=_cfg(), transport=lambda *_a, **_kw: {"response": "x"})
    runner.set_workspace("", None, [], ["RELIANCE"])
    kind, text, _ts = runner.ask_sync("anything")
    assert kind == "ok"


# ---------------------------------------------------------------------------
# Successful path
# ---------------------------------------------------------------------------


def test_successful_response_is_verbatim():
    captured = {}

    def fake_transport(url, body, timeout):
        captured["url"] = url
        captured["body"] = body
        return {"response": "Verbatim model reply.\nLine two."}

    runner = TalkRunner(config=_cfg(), transport=fake_transport)
    runner.set_workspace(
        SAMPLE_WORKSPACE_TEXT, "<html>", _sample_news(), ["RELIANCE"]
    )

    kind, text, _ts = runner.ask_sync("What changed in RELIANCE today?")
    assert kind == "ok"
    assert text == "Verbatim model reply.\nLine two."

    # Adapter must have invoked the transport once with the Ollama body shape.
    body = captured["body"]
    assert set(body.keys()) == {"model", "prompt", "stream"}
    assert body["stream"] is False
    # The prompt must come from build_llm_prompt — all five sections present.
    for section in (
        "SYSTEM RULES",
        "USER QUESTION",
        "OBSERVABLE MARKET DATA",
        "NEWS HEADLINES",
        "RESPONSE CONSTRAINTS",
    ):
        assert section in body["prompt"]
    # Question must appear inside the prompt.
    assert "What changed in RELIANCE today?" in body["prompt"]
    # HTML must NOT leak into the prompt.
    assert "<html>" not in body["prompt"]


def test_empty_model_response_is_replaced_with_placeholder():
    runner = TalkRunner(
        config=_cfg(), transport=lambda *_a, **_kw: {"response": ""}
    )
    runner.set_workspace(
        SAMPLE_WORKSPACE_TEXT, None, _sample_news(), ["RELIANCE"]
    )
    kind, text, _ts = runner.ask_sync("Show INFY activity.")
    assert kind == "ok"
    assert text == "(empty response)"


# ---------------------------------------------------------------------------
# Error / failure paths
# ---------------------------------------------------------------------------


def test_adapter_timeout_surfaces_error():
    def timeout(*_a, **_kw):
        raise socket.timeout("timed out")

    runner = TalkRunner(config=_cfg(), transport=timeout)
    runner.set_workspace(SAMPLE_WORKSPACE_TEXT, None, [], ["RELIANCE"])
    kind, text, _ts = runner.ask_sync("What changed in RELIANCE today?")
    assert kind == "error"
    # Spec wording — friendly translation of the adapter's
    # ``timeout: 5`` token (_cfg() defaults to a 5-second timeout).
    assert text == "Local model request timed out after 5 seconds."


def test_adapter_connection_refused_surfaces_error():
    def dead(*_a, **_kw):
        raise urllib.error.URLError("Connection refused")

    runner = TalkRunner(config=_cfg(), transport=dead)
    runner.set_workspace(SAMPLE_WORKSPACE_TEXT, None, [], ["RELIANCE"])
    kind, text, _ts = runner.ask_sync("question")
    assert kind == "error"
    # Spec wording — friendly translation of the adapter's
    # ``connection_failure`` token; backend is Ollama in _cfg().
    assert text == "Unable to connect to local Ollama runtime."


def test_adapter_malformed_response_surfaces_error():
    def malformed(*_a, **_kw):
        return {"done": True}  # missing 'response'

    runner = TalkRunner(config=_cfg(), transport=malformed)
    runner.set_workspace(SAMPLE_WORKSPACE_TEXT, None, [], ["RELIANCE"])
    kind, text, _ts = runner.ask_sync("question")
    assert kind == "error"
    # Adapter token ``malformed_response: missing_response_field`` is
    # mapped to a single readable line for the response panel.
    assert text == "Local Ollama runtime returned an unreadable response."


def test_forbidden_phrase_in_question_returns_prompt_rejected():
    runner = TalkRunner(config=_cfg(), transport=lambda *_a, **_kw: {"response": "x"})
    runner.set_workspace(SAMPLE_WORKSPACE_TEXT, None, [], ["RELIANCE"])
    kind, text, _ts = runner.ask_sync(
        "Give me a guaranteed buy signal for RELIANCE."
    )
    assert kind == "error"
    assert text.startswith("prompt_rejected")
    assert "guaranteed" in text


# ---------------------------------------------------------------------------
# Context isolation
# ---------------------------------------------------------------------------


def test_clear_workspace_removes_context():
    runner = TalkRunner(config=_cfg(), transport=lambda *_a, **_kw: {"response": "x"})
    runner.set_workspace(SAMPLE_WORKSPACE_TEXT, None, [], ["RELIANCE"])
    assert runner.has_workspace()
    runner.clear_workspace()
    assert not runner.has_workspace()
    kind, text, _ts = runner.ask_sync("question")
    assert kind == "fallback"
    assert text == NO_WORKSPACE_MESSAGE


def test_set_workspace_overrides_previous_context():
    seen = {}

    def fake_transport(url, body, timeout):
        seen["body"] = body
        return {"response": "ok"}

    runner = TalkRunner(config=_cfg(), transport=fake_transport)
    runner.set_workspace("OLD CONTEXT", None, [], ["RELIANCE"])
    runner.set_workspace("NEW CONTEXT", None, [], ["INFY"])
    runner.ask_sync("Show INFY activity.")
    prompt = seen["body"]["prompt"]
    assert "NEW CONTEXT" in prompt
    assert "OLD CONTEXT" not in prompt
    assert "INFY" in prompt


def test_workspace_html_never_leaks_into_prompt():
    seen = {}

    def fake_transport(url, body, timeout):
        seen["body"] = body
        return {"response": "ok"}

    html_blob = "<table id='secret-html-marker'><tr><td>x</td></tr></table>"
    runner = TalkRunner(config=_cfg(), transport=fake_transport)
    runner.set_workspace(SAMPLE_WORKSPACE_TEXT, html_blob, [], ["RELIANCE"])
    runner.ask_sync("question")
    prompt = seen["body"]["prompt"]
    assert "secret-html-marker" not in prompt
    assert "<table" not in prompt


# ---------------------------------------------------------------------------
# Async signals (UI-facing path)
# ---------------------------------------------------------------------------


def _spin_until(predicate, timeout_ms: int = 3000) -> bool:
    """Process Qt events until ``predicate()`` is true or timeout elapses."""
    from time import sleep

    elapsed = 0
    step = 25
    while elapsed < timeout_ms:
        QCoreApplication.processEvents()
        if predicate():
            return True
        sleep(step / 1000)
        elapsed += step
    QCoreApplication.processEvents()
    return predicate()


def _drain_runner(runner: TalkRunner, timeout_ms: int = 2000) -> None:
    """Wait for any pending background thread to finish cleanly."""
    _spin_until(
        lambda: runner._thread is None and runner._worker is None,  # noqa: SLF001
        timeout_ms=timeout_ms,
    )


def test_ask_emits_started_and_finished_ok_signals(qapp):
    runner = TalkRunner(
        config=_cfg(),
        transport=lambda *_a, **_kw: {"response": "async ok"},
    )
    runner.set_workspace(SAMPLE_WORKSPACE_TEXT, None, [], ["RELIANCE"])

    started_hits: list[None] = []
    ok_hits: list[tuple[str, str]] = []
    err_hits: list[tuple[str, str]] = []
    runner.started.connect(lambda: started_hits.append(None))
    runner.finished_ok.connect(lambda t, ts: ok_hits.append((t, ts)))
    runner.finished_error.connect(lambda t, ts: err_hits.append((t, ts)))

    runner.ask("question")

    assert _spin_until(lambda: len(ok_hits) >= 1)
    _drain_runner(runner)
    assert err_hits == []
    assert len(started_hits) == 1
    text, ts = ok_hits[0]
    assert text == "async ok"
    assert ts  # timestamp present


def test_ask_async_empty_question_emits_error_without_starting(qapp):
    runner = TalkRunner(config=_cfg())
    started_hits: list[None] = []
    err_hits: list[tuple[str, str]] = []
    runner.started.connect(lambda: started_hits.append(None))
    runner.finished_error.connect(lambda t, ts: err_hits.append((t, ts)))

    runner.ask("   ")
    QCoreApplication.processEvents()

    assert started_hits == []
    assert len(err_hits) == 1
    assert err_hits[0][0] == EMPTY_QUESTION_MESSAGE


def test_ask_async_no_workspace_emits_finished_ok_fallback_without_starting(qapp):
    runner = TalkRunner(config=_cfg())
    started_hits: list[None] = []
    ok_hits: list[tuple[str, str]] = []
    runner.started.connect(lambda: started_hits.append(None))
    runner.finished_ok.connect(lambda t, ts: ok_hits.append((t, ts)))

    runner.ask("question")
    QCoreApplication.processEvents()

    assert started_hits == []
    assert len(ok_hits) == 1
    assert ok_hits[0][0] == NO_WORKSPACE_MESSAGE


def test_ask_async_error_path(qapp):
    def timeout(*_a, **_kw):
        raise socket.timeout("timed out")

    runner = TalkRunner(config=_cfg(), transport=timeout)
    runner.set_workspace(SAMPLE_WORKSPACE_TEXT, None, [], ["RELIANCE"])

    started_hits: list[None] = []
    err_hits: list[tuple[str, str]] = []
    runner.started.connect(lambda: started_hits.append(None))
    runner.finished_error.connect(lambda t, ts: err_hits.append((t, ts)))

    runner.ask("question")
    assert _spin_until(lambda: len(err_hits) >= 1)
    _drain_runner(runner)
    assert len(started_hits) == 1
    # Friendly translation of the adapter's ``timeout: 5`` token (the
    # _cfg() helper builds a config with timeout_seconds=5.0).
    assert err_hits[0][0] == "Local model request timed out after 5 seconds."
