"""Tests for the unified factual workspace CLI."""

from __future__ import annotations

import re
import sys
from datetime import date
from pathlib import Path
from unittest.mock import patch

import polars as pl
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.news_models import NewsItem, NewsResult  # noqa: E402
from src.workspace import SECTION_RULE, render_workspace  # noqa: E402

TS_RE = re.compile(r"\[\d{2}:\d{2}:\d{2} \d{2}:\d{2}:\d{2}\]")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


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


@pytest.fixture
def fake_install(tmp_path, monkeypatch):
    monkeypatch.setenv("MM_INSTALL_ROOT", str(tmp_path))
    return tmp_path


def _news_result_with_items(symbol: str) -> NewsResult:
    ts = "25:05:26 11:15:42"
    items = [
        NewsItem(
            headline="ACME launches new product",
            source="Wire24",
            url="https://news.example/acme-launch",
            timestamp=ts,
        ),
        NewsItem(
            headline="Analyst update on ACME",
            source="MarketDesk",
            url="https://news.example/acme-update",
            timestamp=ts,
        ),
    ]
    return NewsResult(
        symbol=symbol,
        timestamp=ts,
        count=len(items),
        items=items,
        source_query_url="https://news.example/rss?q=ACME",
        error=None,
    )


def _news_result_empty(symbol: str, error: str = "no_headlines") -> NewsResult:
    return NewsResult(
        symbol=symbol,
        timestamp="25:05:26 11:15:42",
        count=0,
        items=[],
        source_query_url="https://news.example/rss?q=" + symbol,
        error=error,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_two_sections_separated_by_rule(fake_install):
    _write_cash(fake_install, "ACME", [
        _cash_row(date(2026, 5, 19), 100.0),
        _cash_row(date(2026, 5, 20), 101.0),
    ])
    with patch("src.workspace.fetch_symbol_news", return_value=_news_result_with_items("ACME")):
        text = render_workspace("ACME", lookback=5, news_limit=5, news_timeout=5.0)

    assert "SYMBOL: ACME" in text
    assert "CASH" in text
    assert "F&O" in text
    assert "NEWS" in text
    assert SECTION_RULE in text
    obs_pos = text.find("CASH")
    news_pos = text.find("NEWS")
    rule_pos = text.find(SECTION_RULE)
    assert obs_pos < rule_pos < news_pos


def test_news_block_contains_headlines(fake_install):
    _write_cash(fake_install, "ACME", [_cash_row(date(2026, 5, 20), 100.0)])
    with patch("src.workspace.fetch_symbol_news", return_value=_news_result_with_items("ACME")):
        text = render_workspace("ACME", lookback=5, news_limit=5, news_timeout=5.0)

    assert "Source:\nWire24" in text
    assert "Headline:\nACME launches new product" in text
    assert "URL:\nhttps://news.example/acme-launch" in text
    assert "Source:\nMarketDesk" in text


def test_news_block_renders_not_available_for_empty(fake_install):
    _write_cash(fake_install, "ACME", [_cash_row(date(2026, 5, 20), 100.0)])
    with patch("src.workspace.fetch_symbol_news", return_value=_news_result_empty("ACME")):
        text = render_workspace("ACME", lookback=5, news_limit=5, news_timeout=5.0)

    assert "NEWS" in text
    assert "ERROR: no_headlines" in text
    assert "Source:\nNot Available" in text
    assert "Headline:\nNot Available" in text
    assert "URL:\nNot Available" in text


def test_observation_section_for_missing_symbol(fake_install):
    with patch("src.workspace.fetch_symbol_news", return_value=_news_result_empty("NONEXISTENT", error="no_headlines")):
        text = render_workspace("NONEXISTENT", lookback=5, news_limit=5, news_timeout=5.0)

    assert "SYMBOL: NONEXISTENT" in text
    assert "Latest Close:\nNot Available" in text
    assert "NEWS" in text


def test_news_timeout_error_does_not_block_observation(fake_install):
    _write_cash(fake_install, "ACME", [_cash_row(date(2026, 5, 20), 100.0)])
    with patch(
        "src.workspace.fetch_symbol_news",
        return_value=_news_result_empty("ACME", error="timeout"),
    ):
        text = render_workspace("ACME", lookback=5, news_limit=5, news_timeout=0.001)

    assert "Latest Close:\n100.0" in text
    assert "ERROR: timeout" in text


def test_timestamps_in_both_sections(fake_install):
    _write_cash(fake_install, "ACME", [_cash_row(date(2026, 5, 20), 100.0)])
    with patch("src.workspace.fetch_symbol_news", return_value=_news_result_with_items("ACME")):
        text = render_workspace("ACME", lookback=5, news_limit=5, news_timeout=5.0)

    matches = TS_RE.findall(text)
    assert len(matches) >= 2


def test_no_narrative_words_present(fake_install):
    _write_cash(fake_install, "ACME", [_cash_row(date(2026, 5, 20), 100.0)])
    with patch("src.workspace.fetch_symbol_news", return_value=_news_result_with_items("ACME")):
        text = render_workspace("ACME", lookback=5, news_limit=5, news_timeout=5.0).lower()

    forbidden = [
        "bullish",
        "bearish",
        "recommend",
        "buy ",
        "sell ",
        "accumulation",
        "distribution",
        "sentiment",
        "we believe",
        "likely to",
    ]
    for token in forbidden:
        assert token not in text, f"workspace must not emit narrative token: {token!r}"


def test_news_section_after_separator(fake_install):
    _write_cash(fake_install, "ACME", [_cash_row(date(2026, 5, 20), 100.0)])
    with patch("src.workspace.fetch_symbol_news", return_value=_news_result_with_items("ACME")):
        text = render_workspace("ACME", lookback=5, news_limit=5, news_timeout=5.0)
    head, _, tail = text.partition(SECTION_RULE)
    assert "CASH" in head
    assert "NEWS" in tail
