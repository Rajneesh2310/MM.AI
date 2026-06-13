"""Tests for the deterministic text formatter (RELIANCE / INFY / NIFTY-shaped)."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.text_formatter import NA, format_observations  # noqa: E402

TS_LINE = re.compile(r"^\[\d{2}:\d{2}:\d{2} \d{2}:\d{2}:\d{2}\]$")


def _reliance_obs() -> dict:
    return {
        "symbol": "RELIANCE",
        "timestamp": "25:05:26 10:42:32",
        "lookback_sessions": 5,
        "cash": {
            "latest_session": "2026-05-20",
            "previous_session": "2026-05-19",
            "latest_close": 1359.7,
            "previous_close": 1322.7,
            "close_delta": 37.0,
            "latest_volume": 13248515.0,
            "previous_volume": 21665501.0,
            "volume_delta": -8416986.0,
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
            "latest_fo_row_count": 244,
            "previous_fo_row_count": 241,
            "latest_oi_total": 118900500.0,
            "previous_oi_total": 119281500.0,
            "oi_delta": -381000.0,
            "latest_chg_in_oi_total": -381000.0,
            "latest_contracts_total": 831208.0,
            "previous_contracts_total": 495354.0,
            "contracts_delta": 335854.0,
        },
    }


def _infy_obs() -> dict:
    return {
        "symbol": "INFY",
        "timestamp": "25:05:26 10:42:32",
        "lookback_sessions": 5,
        "cash": {
            "latest_session": "2026-05-20",
            "previous_session": "2026-05-19",
            "latest_close": 1193.7,
            "previous_close": 1196.9,
            "close_delta": -3.2000000000000455,
            "latest_volume": 15121010.0,
            "previous_volume": 32175705.0,
            "volume_delta": -17054695.0,
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
            "latest_fo_row_count": 240,
            "previous_fo_row_count": 236,
            "latest_oi_total": 67244000.0,
            "previous_oi_total": 68173600.0,
            "oi_delta": -929600.0,
            "latest_chg_in_oi_total": -929600.0,
            "latest_contracts_total": 275059.0,
            "previous_contracts_total": 421496.0,
            "contracts_delta": -146437.0,
        },
    }


def _nifty_obs() -> dict:
    return {
        "symbol": "NIFTY",
        "timestamp": "25:05:26 10:42:32",
        "lookback_sessions": 5,
        "cash": {
            "latest_session": None,
            "previous_session": None,
            "latest_close": None,
            "previous_close": None,
            "close_delta": None,
            "latest_volume": None,
            "previous_volume": None,
            "volume_delta": None,
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
            "latest_fo_row_count": 1872,
            "previous_fo_row_count": 1950,
            "latest_oi_total": 396523885.0,
            "previous_oi_total": 714002280.0,
            "oi_delta": -317478395.0,
            "latest_chg_in_oi_total": 65799370.0,
            "latest_contracts_total": 44475382.0,
            "previous_contracts_total": 417021327.0,
            "contracts_delta": -372545945.0,
        },
    }


def test_reliance_full_block():
    text = format_observations(_reliance_obs())
    lines = text.splitlines()

    assert TS_LINE.match(lines[0]) is not None
    assert lines[1] == ""
    assert lines[2] == "SYMBOL: RELIANCE"
    assert "CASH" in text
    assert "F&O" in text
    assert "Latest Close:\n1359.7" in text
    assert "Close Delta:\n37.0" in text
    assert "Volume Delta:\n-8416986.0" in text
    assert "OI Delta:\n-381000.0" in text
    assert "Latest Delivery Percent:\nNot Available" in text


def test_infy_rounds_float_artefact():
    text = format_observations(_infy_obs())
    assert "Close Delta:\n-3.2\n" in text
    assert "-3.2000000000000455" not in text
    assert "Volume Delta:\n-17054695.0" in text


def test_nifty_cash_all_not_available():
    text = format_observations(_nifty_obs())
    assert "SYMBOL: NIFTY" in text
    assert text.count(NA) >= 14
    assert "Latest OI Total:\n396523885.0" in text
    assert "OI Delta:\n-317478395.0" in text


def test_timestamp_is_render_time_not_input_timestamp():
    obs = _reliance_obs()
    obs["timestamp"] = "01:01:00 00:00:00"
    text = format_observations(obs)
    assert "01:01:00 00:00:00" not in text.splitlines()[0]
    assert TS_LINE.match(text.splitlines()[0]) is not None


def test_null_renders_as_not_available():
    obs = _reliance_obs()
    obs["cash"]["latest_close"] = None
    text = format_observations(obs)
    assert "Latest Close:\nNot Available" in text


def test_non_numeric_renders_as_not_available():
    obs = _reliance_obs()
    obs["cash"]["latest_close"] = "garbage"
    text = format_observations(obs)
    assert "Latest Close:\nNot Available" in text


def test_int_row_counts_render_without_decimal():
    text = format_observations(_reliance_obs())
    assert "Latest F&O Row Count:\n244" in text
    assert "Previous F&O Row Count:\n241" in text


def test_missing_section_treated_as_empty():
    text = format_observations({"symbol": "RELIANCE"})
    assert "SYMBOL: RELIANCE" in text
    assert "CASH" in text
    assert "F&O" in text
    assert text.count(NA) >= 20


def test_non_dict_input_raises():
    with pytest.raises(TypeError):
        format_observations("not a dict")  # type: ignore[arg-type]


def test_trailing_newline_present():
    text = format_observations(_reliance_obs())
    assert text.endswith("\n")
    assert not text.endswith("\n\n")
