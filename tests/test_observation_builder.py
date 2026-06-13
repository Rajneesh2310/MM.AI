"""Tests for the deterministic observation builder.

Uses temp parquet only. Symbol names RELIANCE / INFY / NIFTY are reused as
test fixtures to mirror the validation set; no real MM data is read here.
"""

from __future__ import annotations

import re
import sys
from datetime import date
from pathlib import Path

import polars as pl
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.observation_builder import TIMESTAMP_FORMAT, build_observations  # noqa: E402
from src.symbol_reader import load_symbol_data  # noqa: E402

TS_RE = re.compile(r"^\d{2}:\d{2}:\d{2} \d{2}:\d{2}:\d{2}$")


def _write_segment(install: Path, segment: str, symbol: str, rows: list[dict]) -> None:
    sym_dir = install / "data" / segment / f"SYMBOL={symbol}"
    sym_dir.mkdir(parents=True, exist_ok=True)
    by_year: dict[int, list[dict]] = {}
    for r in rows:
        by_year.setdefault(r["DATE"].year, []).append(r)
    for year, year_rows in by_year.items():
        df = pl.DataFrame(year_rows).with_columns(pl.lit(year).cast(pl.Int32).alias("YEAR"))
        df.write_parquet(sym_dir / f"YEAR={year}.parquet")


def _cash_row(d: date, close: float, volume: float, deliv_qty=None, deliv_pct=None) -> dict:
    return {
        "SYMBOL": "ACME",
        "DATE": d,
        "OPEN": close - 1.0,
        "HIGH": close + 2.0,
        "LOW": close - 2.0,
        "CLOSE": close,
        "VOLUME": volume,
        "TURNOVER": close * volume,
        "DELIVERY_QTY": deliv_qty,
        "DELIVERY_PERCENT": deliv_pct,
    }


def _fo_row(d: date, opt: str, strike: float, oi: float, contracts: float, chg_oi: float = 0.0) -> dict:
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
        "CONTRACTS": contracts,
        "VAL_INLAKH": 10.0,
        "OPEN_INT": oi,
        "CHG_IN_OI": chg_oi,
    }


@pytest.fixture
def fake_install(tmp_path, monkeypatch):
    monkeypatch.setenv("MM_INSTALL_ROOT", str(tmp_path))
    return tmp_path


# ---------------------------------------------------------------------------
# Structural / null tests
# ---------------------------------------------------------------------------


def test_no_data_returns_all_nulls(fake_install):
    data = load_symbol_data("NIFTY", lookback_sessions=5)
    obs = build_observations(data)

    assert obs["symbol"] == "NIFTY"
    assert TS_RE.match(obs["timestamp"]) is not None
    assert obs["lookback_sessions"] == 5
    for key, value in obs["cash"].items():
        if key.endswith("_session"):
            assert value is None
        elif key.endswith("_row_count"):
            continue
        else:
            assert value is None, f"cash.{key} should be None"
    assert obs["fo"]["latest_session"] is None
    assert obs["fo"]["previous_session"] is None
    assert obs["fo"]["latest_fo_row_count"] == 0
    assert obs["fo"]["previous_fo_row_count"] == 0
    assert obs["fo"]["latest_oi_total"] is None
    assert obs["fo"]["oi_delta"] is None


def test_single_session_only_yields_null_previous(fake_install):
    _write_segment(fake_install, "cash", "INFY", [_cash_row(date(2026, 5, 20), 1200.0, 1_000_000.0)])

    obs = build_observations(load_symbol_data("INFY", lookback_sessions=5))

    cash = obs["cash"]
    assert cash["latest_session"] == "2026-05-20"
    assert cash["previous_session"] is None
    assert cash["latest_close"] == 1200.0
    assert cash["previous_close"] is None
    assert cash["close_delta"] is None
    assert cash["volume_delta"] is None
    assert cash["delivery_qty_delta"] is None


def test_timestamp_matches_documented_format(fake_install):
    obs = build_observations(load_symbol_data("RELIANCE", lookback_sessions=2))
    assert TIMESTAMP_FORMAT == "%d:%m:%y %H:%M:%S"
    assert TS_RE.match(obs["timestamp"]) is not None


# ---------------------------------------------------------------------------
# Arithmetic tests (RELIANCE / INFY / NIFTY shaped fixtures)
# ---------------------------------------------------------------------------


def test_reliance_like_cash_and_fo_deltas(fake_install):
    sym = "RELIANCE"
    cash = [
        _cash_row(date(2026, 5, 19), 1340.0, 12_000_000.0),
        _cash_row(date(2026, 5, 20), 1359.7, 13_248_515.0),
    ]
    fo = [
        _fo_row(date(2026, 5, 19), "CE", 1340.0, 1000.0, 100.0, chg_oi=10.0),
        _fo_row(date(2026, 5, 19), "PE", 1340.0, 1500.0, 150.0, chg_oi=5.0),
        _fo_row(date(2026, 5, 20), "CE", 1360.0, 1200.0, 110.0, chg_oi=200.0),
        _fo_row(date(2026, 5, 20), "PE", 1360.0, 1800.0, 160.0, chg_oi=300.0),
    ]
    _write_segment(fake_install, "cash", sym, cash)
    _write_segment(fake_install, "fo", sym, fo)

    obs = build_observations(load_symbol_data(sym, lookback_sessions=5))

    assert obs["cash"]["latest_close"] == 1359.7
    assert obs["cash"]["previous_close"] == 1340.0
    assert obs["cash"]["close_delta"] == pytest.approx(19.7)
    assert obs["cash"]["latest_volume"] == 13_248_515.0
    assert obs["cash"]["previous_volume"] == 12_000_000.0
    assert obs["cash"]["volume_delta"] == pytest.approx(1_248_515.0)

    assert obs["fo"]["latest_session"] == "2026-05-20"
    assert obs["fo"]["previous_session"] == "2026-05-19"
    assert obs["fo"]["latest_fo_row_count"] == 2
    assert obs["fo"]["previous_fo_row_count"] == 2
    assert obs["fo"]["latest_oi_total"] == pytest.approx(3000.0)
    assert obs["fo"]["previous_oi_total"] == pytest.approx(2500.0)
    assert obs["fo"]["oi_delta"] == pytest.approx(500.0)
    assert obs["fo"]["latest_chg_in_oi_total"] == pytest.approx(500.0)
    assert obs["fo"]["latest_contracts_total"] == pytest.approx(270.0)
    assert obs["fo"]["previous_contracts_total"] == pytest.approx(250.0)
    assert obs["fo"]["contracts_delta"] == pytest.approx(20.0)


def test_infy_like_delivery_deltas(fake_install):
    sym = "INFY"
    cash = [
        _cash_row(date(2026, 5, 19), 1180.0, 14_000_000.0, deliv_qty=5_000_000.0, deliv_pct=35.7),
        _cash_row(date(2026, 5, 20), 1193.7, 15_121_010.0, deliv_qty=5_500_000.0, deliv_pct=36.4),
    ]
    _write_segment(fake_install, "cash", sym, cash)

    obs = build_observations(load_symbol_data(sym, lookback_sessions=5))

    assert obs["cash"]["latest_delivery_qty"] == 5_500_000.0
    assert obs["cash"]["previous_delivery_qty"] == 5_000_000.0
    assert obs["cash"]["delivery_qty_delta"] == pytest.approx(500_000.0)
    assert obs["cash"]["latest_delivery_percent"] == pytest.approx(36.4)
    assert obs["cash"]["previous_delivery_percent"] == pytest.approx(35.7)
    assert obs["cash"]["delivery_percent_delta"] == pytest.approx(0.7, abs=1e-9)


def test_nifty_like_fo_only_no_cash(fake_install):
    sym = "NIFTY"
    fo = [
        _fo_row(date(2026, 5, 19), "CE", 25000.0, 100000.0, 5000.0),
        _fo_row(date(2026, 5, 19), "PE", 25000.0, 110000.0, 5500.0),
        _fo_row(date(2026, 5, 20), "CE", 25000.0, 120000.0, 5800.0),
        _fo_row(date(2026, 5, 20), "PE", 25000.0, 115000.0, 5400.0),
    ]
    _write_segment(fake_install, "fo", sym, fo)

    obs = build_observations(load_symbol_data(sym, lookback_sessions=5))

    assert obs["cash"]["latest_session"] is None
    assert obs["cash"]["latest_close"] is None
    assert obs["cash"]["close_delta"] is None
    assert obs["cash"]["volume_delta"] is None
    assert obs["fo"]["latest_session"] == "2026-05-20"
    assert obs["fo"]["previous_session"] == "2026-05-19"
    assert obs["fo"]["latest_oi_total"] == pytest.approx(235000.0)
    assert obs["fo"]["previous_oi_total"] == pytest.approx(210000.0)
    assert obs["fo"]["oi_delta"] == pytest.approx(25000.0)


def test_non_numeric_value_coerced_to_null(fake_install):
    sym = "RELIANCE"
    rows = [
        _cash_row(date(2026, 5, 19), 100.0, 1000.0),
        _cash_row(date(2026, 5, 20), 101.0, 1100.0),
    ]
    _write_segment(fake_install, "cash", sym, rows)

    obs = build_observations(load_symbol_data(sym, lookback_sessions=2))
    assert obs["cash"]["latest_close"] == 101.0
    assert obs["cash"]["latest_delivery_qty"] is None
    assert obs["cash"]["delivery_qty_delta"] is None


def test_build_observations_rejects_non_symbol_data():
    with pytest.raises(TypeError):
        build_observations({"symbol": "RELIANCE"})  # type: ignore[arg-type]
