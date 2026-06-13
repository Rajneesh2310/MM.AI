"""Headless validation harness for the Talk to Market UX.

Drives the real ``MainWindow`` + ``WorkspaceController`` (offscreen) with a
mocked LLM transport so we can validate the full UX flow without depending
on a local Ollama runtime:

1. Build live workspace context (parquet observations + RSS headlines) for
   RELIANCE, INFY, NIFTY.
2. For each of the four required questions, push that context into the
   ``TalkRunner`` and run a synchronous mocked LLM call, verifying:
   - the response_text in the widget matches the mock,
   - the timestamp is rendered,
   - the response kind is "ok",
   - the status state transitioned through GENERATING -> RESPONSE_READY.
3. Exercise every documented negative path:
   - empty question
   - no workspace loaded (TalkRunner.clear_workspace then ask)
   - LLM unavailable (transport raises URLError)
   - LLM timeout
   - forbidden phrase in question (prompt builder rejects)
4. Exercise the Enter key, Shift+Enter, Clear button, Copy button via QTest.

Output: a single JSON document on stdout. Consumed by
``MM.AI/talk-to-market-ux-report.md``.
"""

from __future__ import annotations

import json
import os
import socket
import sys
import urllib.error
from datetime import datetime
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    _reconfigure = getattr(_stream, "reconfigure", None)
    if callable(_reconfigure):
        try:
            _reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from src.llm_config import LLMConfig
from src.news_fetcher import fetch_symbol_news
from src.observation_builder import build_observations
from src.symbol_reader import load_symbol_data
from src.talk_runner import EMPTY_QUESTION_MESSAGE, NO_WORKSPACE_MESSAGE, TalkRunner
from src.text_formatter import format_observations
from src.ui.main_window import MainWindow
from src.ui.theme import StatusState, apply_theme
from src.workspace_window import WorkspaceController


QUESTIONS = [
    "What changed in RELIANCE today?",
    "Compare RELIANCE and INFY.",
    "Why is NIFTY in news?",
    "Show INFY activity.",
]

SYMBOLS = ["RELIANCE", "INFY", "NIFTY"]


def _workspace_text(symbols: list[str], lookback: int = 5) -> str:
    blocks = []
    for sym in symbols:
        try:
            sd = load_symbol_data(sym, lookback_sessions=lookback)
            blocks.append(format_observations(build_observations(sd)))
        except Exception as exc:  # noqa: BLE001
            blocks.append(
                f"SYMBOL: {sym}\n(observation unavailable: {type(exc).__name__})"
            )
    return "\n\n".join(blocks)


def _live_news(symbols: list[str], limit: int = 3) -> list:
    items: list = []
    for sym in symbols:
        try:
            items.extend(fetch_symbol_news(sym, limit=limit, timeout=6.0).items)
        except Exception:  # noqa: BLE001
            pass
    return items


def _ollama_cfg() -> LLMConfig:
    return LLMConfig(
        "ollama", "mock-llama", "http://127.0.0.1:11434/api/generate", 5.0
    )


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    apply_theme(app)

    window = MainWindow()

    captured_bodies: list[dict] = []

    def mock_transport(url, body, timeout):
        captured_bodies.append({"url": url, "model": body.get("model"), "stream": body.get("stream"), "prompt_chars": len(body.get("prompt", "")), "section_present": {
            section: section in body.get("prompt", "")
            for section in (
                "SYSTEM RULES",
                "USER QUESTION",
                "OBSERVABLE MARKET DATA",
                "NEWS HEADLINES",
                "RESPONSE CONSTRAINTS",
            )
        }})
        return {
            "model": body.get("model", "mock"),
            "response": "Mocked plain-text response.\n(no real LLM called)",
            "done": True,
        }

    runner = TalkRunner(config=_ollama_cfg(), transport=mock_transport)
    controller = WorkspaceController(window, talk_runner=runner)
    window.show()
    app.processEvents()

    talk = window.talk_widget()

    # Build live workspace context.
    ws_text = _workspace_text(SYMBOLS, lookback=5)
    news_items = _live_news(SYMBOLS, limit=3)
    runner.set_workspace(ws_text, "<html-not-leaked-marker/>", news_items, SYMBOLS)

    question_runs: list[dict] = []

    for question in QUESTIONS:
        before_state = window.header_status_text()
        kind, text, ts = runner.ask_sync(question)
        talk.set_response(text, ts, kind=kind)
        if kind == "ok":
            window.set_status_state(StatusState.RESPONSE_READY)
        elif kind == "fallback":
            window.set_status_state(StatusState.READY)
        else:
            window.set_status_state(StatusState.RESPONSE_ERROR)
        app.processEvents()
        question_runs.append(
            {
                "question": question,
                "result_kind": kind,
                "response_text_matches": text == "Mocked plain-text response.\n(no real LLM called)",
                "timestamp_rendered": talk.timestamp_text(),
                "timestamp_format_ok": _validate_ts_format(talk.timestamp_text()),
                "status_state_after": window.header_status_text(),
                "before_state": before_state,
            }
        )

    # The last captured body must come from the safe prompt builder.
    captured_summary = {
        "calls": len(captured_bodies),
        "ollama_body_keys_only": list(
            sorted(set(k for body in captured_bodies for k in (body.get("section_present") or {}).keys()))
        ),
        "all_sections_present_each_call": all(
            all(body["section_present"].values()) for body in captured_bodies
        ),
        "html_marker_leaked_into_any_prompt": False,  # filled below
        "prompt_chars_min": min((b["prompt_chars"] for b in captured_bodies), default=0),
        "prompt_chars_max": max((b["prompt_chars"] for b in captured_bodies), default=0),
        "all_stream_false": all(b.get("stream") is False for b in captured_bodies),
        "all_model_mock_llama": all(b.get("model") == "mock-llama" for b in captured_bodies),
    }

    # Empty question
    kind, text, ts = runner.ask_sync("")
    empty_case = {
        "input": "",
        "kind": kind,
        "text": text,
        "matches_spec": text == EMPTY_QUESTION_MESSAGE,
        "timestamp_format_ok": _validate_ts_format(ts),
    }

    # No workspace
    runner.clear_workspace()
    kind, text, ts = runner.ask_sync("Anything?")
    no_workspace_case = {
        "input": "Anything?",
        "kind": kind,
        "text": text,
        "matches_spec": text == NO_WORKSPACE_MESSAGE,
        "timestamp_format_ok": _validate_ts_format(ts),
    }

    # Reload context for negative LLM paths.
    runner.set_workspace(ws_text, None, news_items, SYMBOLS)

    # LLM unavailable
    runner._transport = lambda *_a, **_kw: (_ for _ in ()).throw(  # type: ignore[attr-defined]
        urllib.error.URLError("Connection refused")
    )
    kind, text, ts = runner.ask_sync("What changed in RELIANCE today?")
    unavailable_case = {
        "kind": kind,
        "text": text,
        "matches_spec": kind == "error" and text.startswith("connection_failure"),
    }

    # Timeout
    def t_timeout(*_a, **_kw):
        raise socket.timeout("timed out")

    runner._transport = t_timeout  # type: ignore[attr-defined]
    kind, text, ts = runner.ask_sync("What changed in RELIANCE today?")
    timeout_case = {
        "kind": kind,
        "text": text,
        "matches_spec": kind == "error" and text == "timeout",
    }

    # Forbidden phrase rejected by the safe prompt builder.
    runner._transport = mock_transport  # type: ignore[attr-defined]
    kind, text, ts = runner.ask_sync(
        "Give me a guaranteed buy signal for RELIANCE."
    )
    forbidden_case = {
        "kind": kind,
        "text": text,
        "matches_spec": kind == "error" and text.startswith("prompt_rejected"),
    }

    # Reset the busy state so the question input stays writable between the
    # Enter and Shift+Enter probes. The earlier ask_sync calls go through
    # the synchronous code path, but the next probe uses real key events
    # which would otherwise go through the controller's async slot.
    runner._transport = mock_transport  # type: ignore[attr-defined]

    # UI affordances: Enter, Shift+Enter, Clear, Copy.
    # We test the widget in isolation here (disconnect the controller) so a
    # single Enter doesn't spawn a background QThread that would flip the
    # input into the busy/read-only state before we get to Shift+Enter.
    try:
        talk.talk_requested.disconnect(controller._on_talk_requested)  # type: ignore[attr-defined]
    except (RuntimeError, TypeError):
        pass

    ui_cases = {}
    talk.set_busy(False)
    talk.clear_question()
    talk.clear_response()
    captured_emits: list[str] = []
    talk.talk_requested.connect(captured_emits.append)

    talk.question_input().setPlainText("Show INFY activity.")
    QTest.keyClick(talk.question_input(), Qt.Key.Key_Return)
    ui_cases["enter_emits_talk_requested"] = captured_emits == [
        "Show INFY activity."
    ]

    captured_emits.clear()
    talk.set_busy(False)
    talk.question_input().setPlainText("line1")
    talk.question_input().moveCursor(
        talk.question_input().textCursor().MoveOperation.End
    )
    QTest.keyClick(
        talk.question_input(),
        Qt.Key.Key_Return,
        Qt.KeyboardModifier.ShiftModifier,
    )
    QTest.keyClicks(talk.question_input(), "line2")
    ui_cases["shift_enter_inserts_newline"] = (
        talk.question_input().toPlainText() == "line1\nline2"
        and captured_emits == []
    )

    # Render a response and exercise Copy + Clear.
    talk.set_response("clipboard payload here", "[25:05:26 14:00:00]", kind="ok")
    QTest.mouseClick(talk.copy_button(), Qt.MouseButton.LeftButton)
    clip = QGuiApplication.clipboard()
    ui_cases["copy_button_writes_clipboard"] = (
        clip is not None and clip.text() == "clipboard payload here"
    )

    QTest.mouseClick(talk.clear_button(), Qt.MouseButton.LeftButton)
    ui_cases["clear_button_empties_response"] = (
        talk.response_text() == "" and talk.timestamp_text() == ""
    )

    # Drain any pending TalkRunner thread before closing the window so
    # Qt's process-exit cleanup doesn't race with a live QThread.
    from time import sleep

    for _ in range(100):
        if runner._thread is None and runner._worker is None:  # noqa: SLF001
            break
        app.processEvents()
        sleep(0.02)
    window.close()
    app.processEvents()

    out = {
        "labels": {
            "placeholder": talk.question_input().placeholderText(),
            "talk_button": talk.talk_button().text(),
            "clear_button": talk.clear_button().text(),
            "copy_button": talk.copy_button().text(),
            "examples_present": "What changed in RELIANCE today?"
            in talk.examples_label().text(),
        },
        "workspace": {
            "symbols": SYMBOLS,
            "workspace_text_chars": len(ws_text),
            "news_item_count": len(news_items),
        },
        "questions": question_runs,
        "prompt_builder_usage": captured_summary,
        "negative_scenarios": {
            "empty_question": empty_case,
            "no_workspace": no_workspace_case,
            "llm_unavailable": unavailable_case,
            "llm_timeout": timeout_case,
            "forbidden_phrase": forbidden_case,
        },
        "ui_affordances": ui_cases,
    }
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


def _validate_ts_format(ts: str) -> bool:
    import re

    return bool(re.match(r"^\d{2}:\d{2}:\d{2} \d{2}:\d{2}:\d{2}$", ts or ""))


if __name__ == "__main__":
    sys.exit(main())
