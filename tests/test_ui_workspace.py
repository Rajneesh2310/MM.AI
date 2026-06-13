"""Headless tests for the MM.AI desktop UI (UX Step 2).

Uses Qt's ``offscreen`` platform plugin so the tests run without a display
server. The ``fetch_symbol_news`` call is mocked to keep tests deterministic
and offline.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sys
from datetime import date
from pathlib import Path
from unittest.mock import patch

import polars as pl
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from src.news_models import NewsItem, NewsResult  # noqa: E402
from src.observation_table import render_observation_html  # noqa: E402
from src.ui.main_window import MainWindow  # noqa: E402
from src.workspace_window import (  # noqa: E402
    WorkspaceController,
    _format_news_html,
    create_workspace_window,
    parse_symbols,
    run_pipeline,
)


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def fake_install(tmp_path, monkeypatch):
    monkeypatch.setenv("MM_INSTALL_ROOT", str(tmp_path))
    return tmp_path


def _cash_row(d: date, close: float) -> dict:
    return {
        "SYMBOL": "ACME",
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


def _write_cash(install: Path, symbol: str, rows: list[dict]) -> None:
    sym_dir = install / "data" / "cash" / f"SYMBOL={symbol}"
    sym_dir.mkdir(parents=True, exist_ok=True)
    by_year: dict[int, list[dict]] = {}
    for r in rows:
        by_year.setdefault(r["DATE"].year, []).append(r)
    for year, year_rows in by_year.items():
        df = pl.DataFrame(year_rows).with_columns(pl.lit(year).cast(pl.Int32).alias("YEAR"))
        df.write_parquet(sym_dir / f"YEAR={year}.parquet")


def _populated_news(symbol: str = "ACME") -> NewsResult:
    ts = "25:05:26 11:24:00"
    return NewsResult(
        symbol=symbol,
        timestamp=ts,
        count=2,
        items=[
            NewsItem(
                headline=f"{symbol} launches new product",
                source="Wire24",
                url=f"https://news.example/{symbol.lower()}-launch",
                timestamp=ts,
            ),
            NewsItem(
                headline=f"Analyst update on {symbol}",
                source="MarketDesk",
                url=f"https://news.example/{symbol.lower()}-update",
                timestamp=ts,
            ),
        ],
        source_query_url=f"https://news.example/rss?q={symbol}",
        error=None,
    )


def _empty_news(symbol: str, error: str = "no_headlines") -> NewsResult:
    return NewsResult(
        symbol=symbol,
        timestamp="25:05:26 11:24:01",
        count=0,
        items=[],
        source_query_url=f"https://news.example/rss?q={symbol}",
        error=error,
    )


# ---------------------------------------------------------------------------
# Symbol parsing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("", []),
        (None, []),
        ("RELIANCE", ["RELIANCE"]),
        ("reliance", ["RELIANCE"]),
        ("  reliance  ", ["RELIANCE"]),
        ("RELIANCE, INFY, NIFTY", ["RELIANCE", "INFY", "NIFTY"]),
        ("reliance,infy ,nifty,", ["RELIANCE", "INFY", "NIFTY"]),
        ("RELIANCE,RELIANCE,INFY", ["RELIANCE", "INFY"]),
        ("RELIANCE;INFY;NIFTY", ["RELIANCE", "INFY", "NIFTY"]),
    ],
)
def test_parse_symbols(raw, expected):
    assert parse_symbols(raw) == expected


# ---------------------------------------------------------------------------
# Layout / defaults
# ---------------------------------------------------------------------------


def test_window_defaults_and_size(qapp):
    window = MainWindow()
    try:
        assert window.windowTitle() == "MM.AI Workspace"
        assert window.size().width() == 1200
        assert window.size().height() == 800
        ph = window.symbol_field().placeholderText()
        assert "Enter symbol" in ph
        assert "RELIANCE, INFY" in ph
        assert window.lookback_field().value() == 5
        assert window.news_limit_field().value() == 5
        assert window.lookback_field().maximum() == 99
        assert window.news_limit_field().maximum() == 99
        assert window.lookback_field().width() <= 64
        assert window.news_limit_field().width() <= 64
        # No "Load Workspace" button anywhere in the search bar.
        from PySide6.QtWidgets import QPushButton

        assert window.findChild(QPushButton, "LoadWorkspaceButton") is None
    finally:
        window.close()


def test_scrollbar_policies(qapp):
    """Observation never scrolls vertically (force off); horizontal stays
    as-needed so multi-symbol overflow remains scrollable. News view never
    shows a manual scrollbar — the ticker drives it.
    """
    window = MainWindow()
    try:
        obs = window.findChild(object, "ObservationView")
        news = window.findChild(object, "NewsView")
        assert obs.verticalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        assert obs.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAsNeeded
        assert news.verticalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        assert news.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    finally:
        window.close()


def test_enter_in_symbol_field_triggers_load(qapp):
    window = MainWindow()
    try:
        emitted: list[tuple] = []
        window.load_requested.connect(lambda *a: emitted.append(a))
        window.symbol_field().setText(" reliance , infy ")
        window.lookback_field().setValue(7)
        window.news_limit_field().setValue(3)
        QTest.keyClick(window.symbol_field(), Qt.Key.Key_Return)
        assert emitted == [("reliance , infy", 7, 3)]
    finally:
        window.close()


def test_enter_in_spinboxes_also_triggers_load(qapp):
    window = MainWindow()
    try:
        emitted: list[tuple] = []
        window.load_requested.connect(lambda *a: emitted.append(a))
        window.symbol_field().setText("RELIANCE")
        QTest.keyClick(window.lookback_field().lineEdit(), Qt.Key.Key_Return)
        QTest.keyClick(window.news_limit_field().lineEdit(), Qt.Key.Key_Return)
        # Qt may fire returnPressed twice per Enter inside a QSpinBox lineEdit;
        # we accept that, the controller debounces it via set_load_enabled.
        assert len(emitted) >= 2
        for sym, lb, nl in emitted:
            assert sym == "RELIANCE"
            assert lb == 5 and nl == 5
    finally:
        window.close()


def test_setters_populate_views(qapp):
    window = MainWindow()
    try:
        window.set_observation_html(
            '<table class="obs"><tr><td>Close</td><td>100.0</td></tr></table>'
        )
        window.set_news_html("<p>Source:<br>Wire24</p>")
        window.set_status("loaded ACME")
        assert "Close" in window.observation_plain_text()
        assert "100.0" in window.observation_plain_text()
        assert "Wire24" in window.news_html()
        assert window.header_status_text() == "loaded ACME"
    finally:
        window.close()


# ---------------------------------------------------------------------------
# Observation HTML table
# ---------------------------------------------------------------------------


def test_observation_table_empty():
    html = render_observation_html([])
    assert "no symbols loaded" in html
    assert "table" not in html.lower() or "<table" not in html.lower()


def test_observation_table_single_symbol():
    obs = {
        "symbol": "RELIANCE",
        "lookback_sessions": 5,
        "cash": {
            "latest_session": "2026-05-20",
            "previous_session": "2026-05-19",
            "latest_close": 1359.7,
            "previous_close": 1322.7,
            "close_delta": 37.0,
            "latest_volume": 12345.0,
            "previous_volume": 11000.0,
            "volume_delta": 1345.0,
            "latest_delivery_qty": None,
            "previous_delivery_qty": None,
            "delivery_qty_delta": None,
            "latest_delivery_percent": None,
            "previous_delivery_percent": None,
            "delivery_percent_delta": None,
        },
        "fo": {
            "latest_session": "2026-05-20",
            "previous_session": "2026-05-19",
            "latest_oi_total": 118_900_500.0,
            "previous_oi_total": 118_000_000.0,
            "oi_delta": 900_500.0,
            "latest_chg_in_oi_total": 5000.0,
            "latest_contracts_total": 250000.0,
            "previous_contracts_total": 248000.0,
            "contracts_delta": 2000.0,
        },
    }
    html = render_observation_html([obs])
    assert "RELIANCE" in html
    assert "CASH" in html
    assert "F&amp;O" in html
    assert "1359.7" in html
    assert "1322.7" in html
    assert "+37.0" in html  # signed delta
    assert "Δ" in html or "&Delta;" in html
    # Row counts must not appear in the table
    assert "Row Count" not in html
    assert "row count" not in html.lower()
    # Symbol header colspans 3 (Previous/Latest/Delta)
    assert html.count("colspan=\"3\"") >= 2  # cash + fo


def test_observation_table_multi_symbol_has_per_symbol_columns():
    obs_a = {
        "symbol": "RELIANCE",
        "cash": {"latest_close": 1359.7, "previous_close": 1322.7, "close_delta": 37.0},
        "fo": {"latest_oi_total": 118_900_500.0},
    }
    obs_b = {
        "symbol": "INFY",
        "cash": {"latest_close": 1193.7, "previous_close": 1196.9, "close_delta": -3.2},
        "fo": {"latest_oi_total": 67_244_000.0},
    }
    obs_c = {
        "symbol": "NIFTY",
        "cash": {},
        "fo": {"latest_oi_total": 396_523_885.0},
    }
    html = render_observation_html([obs_a, obs_b, obs_c])
    assert "RELIANCE" in html
    assert "INFY" in html
    assert "NIFTY" in html
    assert "-3.2" in html
    assert "+37.0" in html
    assert "1193.7" in html
    # 3 symbols x 2 sections (CASH + F&O) = 6 "Previous"/"Latest" headers each.
    assert html.count(">Previous<") == 6
    assert html.count(">Latest<") == 6


def test_observation_table_treats_nulls_as_not_available():
    obs = {"symbol": "ACME", "cash": {}, "fo": {}}
    html = render_observation_html([obs])
    assert "Not Available" in html
    assert "None" not in html


# ---------------------------------------------------------------------------
# News HTML rendering (multi-symbol aware)
# ---------------------------------------------------------------------------


def test_news_html_single_result_legacy_signature():
    html = _format_news_html(_populated_news())
    assert html.count("<a href=") == 2


def test_news_html_multi_symbol_lists_each_symbol_header():
    results = [_populated_news("RELIANCE"), _populated_news("INFY")]
    html = _format_news_html(results)
    assert "RELIANCE" in html
    assert "INFY" in html
    assert html.count("<a href=") == 4


def test_news_html_does_not_display_url_line():
    """URL text must not appear as a visible field; the headline itself is
    the clickable anchor."""
    html = _format_news_html(_populated_news("ACME"))
    # No "URL:" label anywhere in the rendered block.
    assert "URL:" not in html
    # The anchor wraps the headline text, not the URL string.
    assert ">https://news.example/" not in html
    assert "ACME launches new product</a>" in html


def test_news_html_headline_is_the_clickable_anchor():
    item = NewsItem(
        headline="A specific clickable headline",
        source="Wire24",
        url="https://news.example/specific",
        timestamp="25:05:26 12:00:00",
    )
    result = NewsResult(
        symbol="ACME",
        timestamp="25:05:26 12:00:00",
        count=1,
        items=[item],
        source_query_url="",
    )
    html = _format_news_html(result)
    assert 'href="https://news.example/specific"' in html
    assert "A specific clickable headline</a>" in html
    # URL string never appears as displayed text.
    assert ">https://news.example/specific<" not in html


def test_news_html_empty_renders_not_available():
    html = _format_news_html([_empty_news("ACME")])
    assert "Not Available" in html
    assert "<a href=" not in html
    assert "ERROR: no_headlines" in html


def test_news_html_escapes_unsafe_characters():
    item = NewsItem(
        headline="<script>alert('xss')</script>",
        source="<b>EvilWire</b>",
        url="https://news.example/x?q=<>",
        timestamp="25:05:26 11:24:02",
    )
    result = NewsResult(
        symbol="ACME",
        timestamp="25:05:26 11:24:02",
        count=1,
        items=[item],
        source_query_url="",
    )
    html = _format_news_html(result)
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "&lt;b&gt;EvilWire" in html


# ---------------------------------------------------------------------------
# Pipeline runs (mocked network) — single + multi
# ---------------------------------------------------------------------------


def test_pipeline_single_symbol(fake_install):
    _write_cash(fake_install, "RELIANCE", [
        _cash_row(date(2026, 5, 19), 1322.7),
        _cash_row(date(2026, 5, 20), 1359.7),
    ])
    with patch(
        "src.workspace_window.fetch_symbol_news",
        return_value=_populated_news("RELIANCE"),
    ):
        obs_html, news_html, news_results = run_pipeline(
            "RELIANCE", lookback=5, news_limit=5, news_timeout=1.0
        )
    assert "RELIANCE" in obs_html
    assert "1359.7" in obs_html
    assert "+37.0" in obs_html
    assert news_results[0].count == 2
    assert "<a href=" in news_html


def test_pipeline_multi_symbol_comma_separated(fake_install):
    _write_cash(fake_install, "RELIANCE", [
        _cash_row(date(2026, 5, 19), 1322.7),
        _cash_row(date(2026, 5, 20), 1359.7),
    ])
    _write_cash(fake_install, "INFY", [
        _cash_row(date(2026, 5, 19), 1196.9),
        _cash_row(date(2026, 5, 20), 1193.7),
    ])
    with patch(
        "src.workspace_window.fetch_symbol_news",
        side_effect=lambda s, **kw: _populated_news(s),
    ):
        obs_html, news_html, news_results = run_pipeline(
            "RELIANCE, INFY, NIFTY",
            lookback=5,
            news_limit=5,
            news_timeout=1.0,
        )
    assert "RELIANCE" in obs_html and "INFY" in obs_html and "NIFTY" in obs_html
    assert "1359.7" in obs_html and "1193.7" in obs_html
    assert len(news_results) == 3
    assert news_html.count("<a href=") == 6


def test_pipeline_nonexistent_symbol(fake_install):
    with patch(
        "src.workspace_window.fetch_symbol_news",
        return_value=_empty_news("NONEXISTENT_SYM_123"),
    ):
        obs_html, news_html, news_results = run_pipeline(
            "NONEXISTENT_SYM_123", lookback=5, news_limit=5, news_timeout=1.0
        )
    assert "NONEXISTENT_SYM_123" in obs_html
    assert obs_html.count("Not Available") >= 5
    assert news_results[0].count == 0
    assert news_results[0].error == "no_headlines"
    assert "<a href=" not in news_html


def test_pipeline_news_timeout(fake_install):
    _write_cash(fake_install, "RELIANCE", [_cash_row(date(2026, 5, 20), 100.0)])
    with patch(
        "src.workspace_window.fetch_symbol_news",
        return_value=_empty_news("RELIANCE", error="timeout"),
    ):
        _, news_html, news_results = run_pipeline(
            "RELIANCE", lookback=5, news_limit=5, news_timeout=0.001
        )
    assert news_results[0].error == "timeout"
    assert "ERROR: timeout" in news_html


# ---------------------------------------------------------------------------
# Controller behaviour
# ---------------------------------------------------------------------------


def test_controller_rejects_blank_symbol(qapp, fake_install):
    window, controller = create_workspace_window()
    try:
        with patch("src.workspace_window.fetch_symbol_news") as mock_fetch:
            window.symbol_field().setText("   ")
            QTest.keyClick(window.symbol_field(), Qt.Key.Key_Return)
            qapp.processEvents()
            mock_fetch.assert_not_called()
            status = window.header_status_text().lower()
            assert "enter at least one symbol" in status or "blank" in status
    finally:
        window.close()
        del controller


def test_controller_rejects_only_punctuation_symbol(qapp, fake_install):
    window, controller = create_workspace_window()
    try:
        with patch("src.workspace_window.fetch_symbol_news") as mock_fetch:
            window.symbol_field().setText(" , , ,")
            QTest.keyClick(window.symbol_field(), Qt.Key.Key_Return)
            qapp.processEvents()
            mock_fetch.assert_not_called()
            assert "enter at least one symbol" in window.header_status_text().lower()
    finally:
        window.close()
        del controller


# ---------------------------------------------------------------------------
# News ticker
# ---------------------------------------------------------------------------


def test_news_ticker_pauses_on_enter_event(qapp):
    from PySide6.QtCore import QEvent, QPointF
    from PySide6.QtGui import QEnterEvent

    window = MainWindow()
    try:
        ticker = window.news_ticker()
        assert ticker.is_paused() is False
        # Synthesise a mouse-enter event into the news view to trigger pause.
        view = window.findChild(object, "NewsView")
        ev = QEnterEvent(QPointF(1, 1), QPointF(1, 1), QPointF(1, 1))
        qapp.sendEvent(view, ev)
        assert ticker.is_paused() is True
        leave = QEvent(QEvent.Type.Leave)
        qapp.sendEvent(view, leave)
        assert ticker.is_paused() is False
    finally:
        window.close()
