"""Integration tests for the Talk-to-Market automatic symbol-extraction flow.

These tests drive the real ``WorkspaceController`` (no mocks for it) but
swap out the two slow boundaries:

* ``fetch_symbol_news`` — replaced with a deterministic in-memory stub so
  no HTTP traffic is required.
* The LLM transport — a callable that captures the request body and
  returns a canned ``{"response": "..."}`` Ollama-shaped dict so the
  adapter completes without touching a real model.

What we verify:

1. Lowercase symbols inside a question (``"compare nifty and reliance"``)
   are extracted, the workspace pipeline auto-loads them, observation +
   news panels are populated, and the LLM response is finally rendered.
2. The status bar passes through the spec-mandated terminal-style
   tokens (``EXTRACTING SYMBOLS...``, ``LOADING NIFTY, RELIANCE...``,
   ``WORKSPACE READY``, ``GENERATING MARKET RESPONSE...``,
   ``MARKET RESPONSE READY``).
3. When a workspace is already loaded with the *same* symbols mentioned
   in the question, no reload is triggered.
4. When a workspace is already loaded but the question mentions
   *additional* symbols, the union is loaded before the LLM call.
5. ``"what changed today?"`` (no symbols, no workspace) still surfaces
   the existing no-workspace fallback.
6. The deterministic ``build_llm_prompt -> generate_llm_response``
   pipeline is exercised — the prompt body received by the transport
   contains all five canonical sections.
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import date
from pathlib import Path
from unittest.mock import patch

import polars as pl
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication

from src import symbol_catalog
from src.llm_config import LLMConfig
from src.news_models import NewsItem, NewsResult
from src.talk_runner import NO_WORKSPACE_MESSAGE, TalkRunner
from src.ui.main_window import MainWindow
from src.ui.theme import StatusState
from src.workspace_window import WorkspaceController


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication(sys.argv)
    yield app


@pytest.fixture
def fake_install(tmp_path, monkeypatch):
    """Stand up a fake MM install with cash parquet + JSON catalogue."""
    monkeypatch.setenv("MM_INSTALL_ROOT", str(tmp_path))
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "cash_symbols.json").write_text(
        json.dumps(["RELIANCE", "INFY", "TCS"]),
        encoding="utf-8",
    )
    (tmp_path / "data" / "fo_symbols.json").write_text(
        json.dumps(["NIFTY", "BANKNIFTY", "RELIANCE", "INFY"]),
        encoding="utf-8",
    )

    def _cash_row(d: date, close: float) -> dict:
        return {
            "SYMBOL": "X",
            "DATE": d,
            "OPEN": close - 1.0,
            "HIGH": close + 1.0,
            "LOW": close - 1.5,
            "CLOSE": close,
            "VOLUME": 1000.0,
            "TURNOVER": close * 1000.0,
            "DELIVERY_QTY": None,
            "DELIVERY_PERCENT": None,
        }

    def _write_cash(symbol: str, rows: list[dict]) -> None:
        sym_dir = tmp_path / "data" / "cash" / f"SYMBOL={symbol}"
        sym_dir.mkdir(parents=True, exist_ok=True)
        for r in rows:
            r["SYMBOL"] = symbol
        df = (
            pl.DataFrame(rows)
            .with_columns(pl.lit(rows[0]["DATE"].year).cast(pl.Int32).alias("YEAR"))
        )
        df.write_parquet(sym_dir / f"YEAR={rows[0]['DATE'].year}.parquet")

    _write_cash(
        "RELIANCE",
        [_cash_row(date(2026, 5, 19), 1322.7), _cash_row(date(2026, 5, 20), 1359.7)],
    )
    _write_cash(
        "INFY",
        [_cash_row(date(2026, 5, 19), 1196.9), _cash_row(date(2026, 5, 20), 1193.7)],
    )
    _write_cash(
        "NIFTY",
        [_cash_row(date(2026, 5, 19), 24500.0), _cash_row(date(2026, 5, 20), 24700.0)],
    )

    symbol_catalog.clear_cache()
    yield tmp_path
    symbol_catalog.clear_cache()


def _stub_news(symbol: str, **_kw) -> NewsResult:
    return NewsResult(
        symbol=symbol,
        timestamp="25:05:26 14:00:00",
        count=1,
        items=[
            NewsItem(
                headline=f"{symbol} headline alpha",
                source="WireTest",
                url=f"https://news.example/{symbol.lower()}-1",
                timestamp="25:05:26 14:00:00",
            )
        ],
        source_query_url=f"https://news.example/rss?q={symbol}",
    )


@pytest.fixture
def llm_transport():
    """Captures the body sent to the (fake) Ollama endpoint."""

    captured: list[dict] = []

    def transport(url, body, timeout):
        captured.append({"url": url, "body": body, "timeout": timeout})
        return {"response": "OK: deterministic test reply."}

    transport.captured = captured  # type: ignore[attr-defined]
    return transport


def _local_cfg() -> LLMConfig:
    return LLMConfig(
        "ollama", "mock-model", "http://127.0.0.1:11434/api/generate", 5.0
    )


def _spin_until(qapp, predicate, timeout_ms: int = 4000) -> bool:
    """Process Qt events until ``predicate()`` returns truthy, or timeout."""
    deadline = time.monotonic() + (timeout_ms / 1000.0)
    while time.monotonic() < deadline:
        qapp.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    qapp.processEvents()
    return bool(predicate())


def _drain_threads(qapp, controller, timeout_ms: int = 4000) -> None:
    """Wait for the pipeline + Talk threads to finish."""
    runner = controller.talk_runner()
    deadline = time.monotonic() + (timeout_ms / 1000.0)
    while time.monotonic() < deadline:
        qapp.processEvents()
        if controller._thread is None and runner._thread is None:
            return
        time.sleep(0.01)
    # Give Qt a final tick to drain pending deleteLater calls.
    qapp.processEvents()


def _make_controller(transport, *, parent_runner_kwargs=None):
    """Create a ``MainWindow`` + ``WorkspaceController`` wired to a test
    ``TalkRunner`` that uses the supplied ``transport``."""
    window = MainWindow()
    runner = TalkRunner(parent=window, config=_local_cfg(), transport=transport)
    if parent_runner_kwargs is not None:
        runner.set_workspace(**parent_runner_kwargs)
    controller = WorkspaceController(window, talk_runner=runner)
    return window, controller, runner


# ---------------------------------------------------------------------------
# 1. Lowercase auto-load chain
# ---------------------------------------------------------------------------


def test_compare_nifty_and_reliance_auto_loads_then_talks(
    qapp, fake_install, llm_transport
):
    window, controller, runner = _make_controller(llm_transport)

    ok_hits: list[tuple[str, str]] = []
    runner.finished_ok.connect(lambda t, s: ok_hits.append((t, s)))

    try:
        with patch(
            "src.workspace_window.fetch_symbol_news",
            side_effect=lambda s, **kw: _stub_news(s),
        ):
            controller._on_talk_requested("compare nifty and reliance")
            assert _spin_until(qapp, lambda: bool(ok_hits), timeout_ms=8000)

        # 1a) Both symbols were loaded (union order: extracted only since
        # nothing was loaded before).
        assert controller._last_symbols == ["NIFTY", "RELIANCE"]

        # 1b) Symbol bar reflects the auto-loaded symbols.
        assert window.symbol_field().text() == "NIFTY, RELIANCE"

        # 1c) Observation panel was populated.
        obs_text = window.observation_plain_text()
        assert "NIFTY" in obs_text
        assert "RELIANCE" in obs_text

        # 1d) News panel was populated for both symbols.
        news_html = window.news_html()
        assert "NIFTY headline alpha" in news_html
        assert "RELIANCE headline alpha" in news_html

        # 1e) LLM response was rendered (not the no-workspace fallback).
        assert ok_hits[0][0] == "OK: deterministic test reply."
        assert NO_WORKSPACE_MESSAGE not in window.header_status_text()

        # 1f) The LLM transport was called with a safe-prompt-builder payload.
        assert len(llm_transport.captured) == 1
        body = llm_transport.captured[0]["body"]
        prompt = body["prompt"]
        for section in (
            "SYSTEM RULES",
            "USER QUESTION",
            "OBSERVABLE MARKET DATA",
            "NEWS HEADLINES",
            "RESPONSE CONSTRAINTS",
        ):
            assert section in prompt
        assert "compare nifty and reliance" in prompt.lower()

    finally:
        _drain_threads(qapp, controller)
        window.close()


# ---------------------------------------------------------------------------
# 2. Status state transitions during the auto-load chain
# ---------------------------------------------------------------------------


def test_status_states_during_auto_load(qapp, fake_install, llm_transport):
    window, controller, runner = _make_controller(llm_transport)

    transitions: list[str] = []
    orig = window.set_status_state

    def spy_state(state, message=None, *, header_override=None):
        transitions.append(header_override if header_override is not None else state)
        orig(state, message, header_override=header_override)

    window.set_status_state = spy_state  # type: ignore[assignment]

    try:
        with patch(
            "src.workspace_window.fetch_symbol_news",
            side_effect=lambda s, **kw: _stub_news(s),
        ):
            controller._on_talk_requested("Show INFY activity")
            _spin_until(
                qapp,
                lambda: window.header_status_text() == StatusState.RESPONSE_READY,
                timeout_ms=8000,
            )

        # The Talk auto-load path emits an EXTRACTING_SYMBOLS pulse first,
        # then a literal "LOADING INFY..." header, then WORKSPACE_READY,
        # then GENERATING, then RESPONSE_READY.
        assert StatusState.EXTRACTING_SYMBOLS in transitions
        assert "LOADING INFY..." in transitions
        assert StatusState.WORKSPACE_READY in transitions
        assert StatusState.GENERATING in transitions
        assert StatusState.RESPONSE_READY in transitions

        # Order check: EXTRACTING comes before LOADING, LOADING before READY.
        i_ex = transitions.index(StatusState.EXTRACTING_SYMBOLS)
        i_ld = transitions.index("LOADING INFY...")
        i_wr = transitions.index(StatusState.WORKSPACE_READY)
        i_gn = transitions.index(StatusState.GENERATING)
        i_rr = transitions.index(StatusState.RESPONSE_READY)
        assert i_ex < i_ld < i_wr < i_gn < i_rr

    finally:
        _drain_threads(qapp, controller)
        window.close()


# ---------------------------------------------------------------------------
# 3. Workspace already loaded with the SAME symbols -> no reload
# ---------------------------------------------------------------------------


def test_already_loaded_same_symbols_skips_reload(
    qapp, fake_install, llm_transport
):
    window, controller, runner = _make_controller(
        llm_transport,
        parent_runner_kwargs=dict(
            workspace_text="SYMBOL: RELIANCE\nCLOSE: 1359.7\n",
            workspace_html="<p>RELIANCE</p>",
            news_items=[_stub_news("RELIANCE")],
            symbols=["RELIANCE"],
        ),
    )
    controller._last_symbols = ["RELIANCE"]

    pipeline_calls = []

    def _no_call(*_a, **_kw):
        pipeline_calls.append(_a)
        raise AssertionError("no pipeline reload expected")

    ok_hits: list[tuple[str, str]] = []
    runner.finished_ok.connect(lambda t, s: ok_hits.append((t, s)))

    try:
        with patch("src.workspace_window.fetch_symbol_news", side_effect=_no_call):
            controller._on_talk_requested("What changed in RELIANCE today?")
            assert _spin_until(qapp, lambda: bool(ok_hits), timeout_ms=4000)

        assert controller._last_symbols == ["RELIANCE"]
        assert pipeline_calls == []
        assert ok_hits[0][0] == "OK: deterministic test reply."
    finally:
        _drain_threads(qapp, controller)
        window.close()


# ---------------------------------------------------------------------------
# 4. Workspace loaded -> question adds a new symbol -> union reload
# ---------------------------------------------------------------------------


def test_loaded_workspace_extended_with_question_symbols(
    qapp, fake_install, llm_transport
):
    window, controller, runner = _make_controller(
        llm_transport,
        parent_runner_kwargs=dict(
            workspace_text="SYMBOL: RELIANCE\n",
            workspace_html="<p>R</p>",
            news_items=[],
            symbols=["RELIANCE"],
        ),
    )
    controller._last_symbols = ["RELIANCE"]

    fetched: list[str] = []

    def stub_news(symbol, **_kw):
        fetched.append(symbol)
        return _stub_news(symbol)

    ok_hits: list[tuple[str, str]] = []
    runner.finished_ok.connect(lambda t, s: ok_hits.append((t, s)))

    try:
        with patch("src.workspace_window.fetch_symbol_news", side_effect=stub_news):
            controller._on_talk_requested("compare reliance and infy")
            assert _spin_until(qapp, lambda: bool(ok_hits), timeout_ms=8000)

        # Union: RELIANCE preserved first, then INFY added.
        assert controller._last_symbols == ["RELIANCE", "INFY"]
        assert set(fetched) == {"RELIANCE", "INFY"}
        assert ok_hits[0][0] == "OK: deterministic test reply."
    finally:
        _drain_threads(qapp, controller)
        window.close()


# ---------------------------------------------------------------------------
# 5. Conversational question + no workspace -> existing no-workspace fallback
# ---------------------------------------------------------------------------


def test_no_workspace_no_symbols_falls_back(
    qapp, fake_install, llm_transport
):
    window, controller, runner = _make_controller(llm_transport)

    ok_hits: list[tuple[str, str]] = []
    runner.finished_ok.connect(lambda t, s: ok_hits.append((t, s)))

    try:
        controller._on_talk_requested("what changed today?")
        assert _spin_until(qapp, lambda: bool(ok_hits), timeout_ms=2000)

        # No symbols extracted -> no auto-load -> TalkRunner returns the
        # no-workspace fallback message.
        assert ok_hits[0][0] == NO_WORKSPACE_MESSAGE
        assert controller._last_symbols == []
        assert llm_transport.captured == []  # LLM never called
    finally:
        _drain_threads(qapp, controller)
        window.close()


# ---------------------------------------------------------------------------
# 6. Empty question still produces the empty-question error verbatim
# ---------------------------------------------------------------------------


def test_empty_question_routes_through_runner(qapp, fake_install, llm_transport):
    window, controller, runner = _make_controller(llm_transport)

    err_hits: list[tuple[str, str]] = []
    runner.finished_error.connect(lambda t, s: err_hits.append((t, s)))

    try:
        controller._on_talk_requested("   ")
        assert _spin_until(qapp, lambda: bool(err_hits), timeout_ms=1000)

        from src.talk_runner import EMPTY_QUESTION_MESSAGE

        assert err_hits[0][0] == EMPTY_QUESTION_MESSAGE
        assert llm_transport.captured == []
    finally:
        _drain_threads(qapp, controller)
        window.close()
