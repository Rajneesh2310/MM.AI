"""Tests for MM.AI symbol_reader — temp parquet only, no real MM install."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import polars as pl
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.symbol_reader import load_symbol_data  # noqa: E402


def _write_segment(install: Path, segment: str, symbol: str, rows: list[dict]) -> None:
    sym_dir = install / "data" / segment / f"SYMBOL={symbol}"
    sym_dir.mkdir(parents=True, exist_ok=True)
    by_year: dict[int, list[dict]] = {}
    for r in rows:
        by_year.setdefault(r["DATE"].year, []).append(r)
    for year, year_rows in by_year.items():
        df = pl.DataFrame(year_rows).with_columns(pl.lit(year).cast(pl.Int32).alias("YEAR"))
        df.write_parquet(sym_dir / f"YEAR={year}.parquet")


def _cash_row(d: date, close: float) -> dict:
    return {
        "SYMBOL": "ACME",
        "DATE": d,
        "OPEN": close - 1.0,
        "HIGH": close + 2.0,
        "LOW": close - 2.0,
        "CLOSE": close,
        "VOLUME": 1000.0,
        "TURNOVER": close * 1000.0,
        "DELIVERY_QTY": None,
        "DELIVERY_PERCENT": None,
    }


def _fo_row(d: date, opt: str, strike: float, oi: float) -> dict:
    return {
        "INSTRUMENT": "OPTSTK",
        "SYMBOL": "ACME",
        "DATE": d,
        "EXPIRY_DT": date(2026, 1, 29),
        "STRIKE_PR": strike,
        "OPTION_TYP": opt,
        "OPEN": 5.0,
        "HIGH": 6.0,
        "LOW": 4.5,
        "CLOSE": 5.5,
        "SETTLE_PR": 5.5,
        "CONTRACTS": 200.0,
        "VAL_INLAKH": 10.0,
        "OPEN_INT": oi,
        "CHG_IN_OI": 50.0,
    }


@pytest.fixture
def fake_install(tmp_path, monkeypatch):
    monkeypatch.setenv("MM_INSTALL_ROOT", str(tmp_path))
    return tmp_path


def test_empty_when_no_parquet(fake_install):
    data = load_symbol_data("RELIANCE", lookback_sessions=5)
    assert data.symbol == "RELIANCE"
    assert data.lookback_sessions == 5
    assert data.cash.latest_session is None
    assert data.cash.latest_row is None
    assert data.cash.previous_sessions == []
    assert data.cash.previous_rows == []
    assert data.fo.latest_session is None
    assert data.fo.latest_session_rows == []
    assert data.fo.previous_session_rows == []


def test_cash_only_returns_latest_and_previous(fake_install):
    rows = [
        _cash_row(date(2026, 1, 2), 100.0),
        _cash_row(date(2026, 1, 3), 102.0),
        _cash_row(date(2026, 1, 6), 105.0),
    ]
    _write_segment(fake_install, "cash", "ACME", rows)

    data = load_symbol_data("ACME", lookback_sessions=3)

    assert data.cash.latest_session == "2026-01-06"
    assert data.cash.latest_row is not None
    assert data.cash.latest_row["CLOSE"] == 105.0
    assert data.cash.latest_row["DATE"] == "2026-01-06"
    assert data.cash.previous_sessions == ["2026-01-03", "2026-01-02"]
    assert len(data.cash.previous_rows) == 2
    assert data.cash.previous_rows[0]["DATE"] == "2026-01-03"
    assert data.cash.previous_rows[1]["DATE"] == "2026-01-02"
    assert data.fo.latest_session is None


def test_cash_and_fo_extracts_both_segments(fake_install):
    cash = [
        _cash_row(date(2026, 1, 5), 100.0),
        _cash_row(date(2026, 1, 6), 102.0),
    ]
    fo = [
        _fo_row(date(2026, 1, 5), "CE", 100.0, 1000.0),
        _fo_row(date(2026, 1, 5), "PE", 100.0, 800.0),
        _fo_row(date(2026, 1, 6), "CE", 100.0, 1100.0),
        _fo_row(date(2026, 1, 6), "PE", 100.0, 900.0),
    ]
    _write_segment(fake_install, "cash", "ACME", cash)
    _write_segment(fake_install, "fo", "ACME", fo)

    data = load_symbol_data("ACME", lookback_sessions=2)

    assert data.cash.latest_session == "2026-01-06"
    assert data.cash.previous_sessions == ["2026-01-05"]
    assert data.fo.latest_session == "2026-01-06"
    assert data.fo.previous_sessions == ["2026-01-05"]
    assert len(data.fo.latest_session_rows) == 2
    assert len(data.fo.previous_session_rows) == 2
    assert {r["OPTION_TYP"] for r in data.fo.latest_session_rows} == {"CE", "PE"}


def test_lookback_clamped_to_one(fake_install):
    _write_segment(fake_install, "cash", "ACME", [_cash_row(date(2026, 1, 2), 100.0)])

    data = load_symbol_data("ACME", lookback_sessions=0)

    assert data.lookback_sessions == 1
    assert data.cash.latest_session == "2026-01-02"
    assert data.cash.previous_sessions == []


def test_symbol_is_uppercased_and_stripped(fake_install):
    _write_segment(fake_install, "cash", "ACME", [_cash_row(date(2026, 1, 2), 100.0)])

    data = load_symbol_data("  acme  ", lookback_sessions=1)

    assert data.symbol == "ACME"
    assert data.cash.latest_session == "2026-01-02"


def test_blank_symbol_raises(fake_install):
    with pytest.raises(ValueError):
        load_symbol_data("   ", lookback_sessions=3)


def test_multi_year_shards_are_merged(fake_install):
    rows = [
        _cash_row(date(2025, 12, 30), 90.0),
        _cash_row(date(2025, 12, 31), 92.0),
        _cash_row(date(2026, 1, 2), 95.0),
    ]
    _write_segment(fake_install, "cash", "ACME", rows)

    data = load_symbol_data("ACME", lookback_sessions=3)

    assert data.cash.latest_session == "2026-01-02"
    assert data.cash.previous_sessions == ["2025-12-31", "2025-12-30"]
