"""Deterministic observable-data builder for MM.AI.

Converts a :class:`SymbolData` extract (see ``symbol_reader.load_symbol_data``)
into a structured dictionary of observable facts. Every value is either:

* taken directly from a parquet row (latest or explicit previous session),
* an explicit difference of two parquet values, or
* a sum of one column on one named session, or
* a row count.

No interpretation, narrative, prediction, recommendation, probability, or
hidden-intent inference is produced.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any

from .models import CashData, FoData, SymbolData

TIMESTAMP_FORMAT = "%d:%m:%y %H:%M:%S"


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(out) or math.isinf(out):
        return None
    return out


def _delta(latest: float | None, previous: float | None) -> float | None:
    if latest is None or previous is None:
        return None
    return latest - previous


def _column_sum(rows: list[dict[str, Any]], column: str) -> float | None:
    if not rows:
        return None
    values = [_to_float(r.get(column)) for r in rows]
    values = [v for v in values if v is not None]
    if not values:
        return None
    return sum(values)


def _rows_for_session(rows: list[dict[str, Any]], session: str | None) -> list[dict[str, Any]]:
    if not session or not rows:
        return []
    return [r for r in rows if str(r.get("DATE")) == session]


def _previous_cash_row(cash: CashData) -> tuple[str | None, dict[str, Any] | None]:
    if not cash.previous_sessions or not cash.previous_rows:
        return None, None
    return cash.previous_sessions[0], cash.previous_rows[0]


def _build_cash(cash: CashData) -> dict[str, Any]:
    latest = cash.latest_row or {}
    previous_session, previous = _previous_cash_row(cash)
    previous = previous or {}

    latest_close = _to_float(latest.get("CLOSE"))
    previous_close = _to_float(previous.get("CLOSE"))
    latest_volume = _to_float(latest.get("VOLUME"))
    previous_volume = _to_float(previous.get("VOLUME"))
    latest_delivery_qty = _to_float(latest.get("DELIVERY_QTY"))
    previous_delivery_qty = _to_float(previous.get("DELIVERY_QTY"))
    latest_delivery_percent = _to_float(latest.get("DELIVERY_PERCENT"))
    previous_delivery_percent = _to_float(previous.get("DELIVERY_PERCENT"))

    return {
        "latest_session": cash.latest_session,
        "previous_session": previous_session,
        "latest_close": latest_close,
        "previous_close": previous_close,
        "close_delta": _delta(latest_close, previous_close),
        "latest_volume": latest_volume,
        "previous_volume": previous_volume,
        "volume_delta": _delta(latest_volume, previous_volume),
        "latest_delivery_qty": latest_delivery_qty,
        "previous_delivery_qty": previous_delivery_qty,
        "delivery_qty_delta": _delta(latest_delivery_qty, previous_delivery_qty),
        "latest_delivery_percent": latest_delivery_percent,
        "previous_delivery_percent": previous_delivery_percent,
        "delivery_percent_delta": _delta(latest_delivery_percent, previous_delivery_percent),
    }


def _build_fo(fo: FoData) -> dict[str, Any]:
    latest_rows = list(fo.latest_session_rows)
    previous_session = fo.previous_sessions[0] if fo.previous_sessions else None
    previous_rows = _rows_for_session(fo.previous_session_rows, previous_session)

    latest_oi_total = _column_sum(latest_rows, "OPEN_INT")
    previous_oi_total = _column_sum(previous_rows, "OPEN_INT")
    latest_chg_in_oi_total = _column_sum(latest_rows, "CHG_IN_OI")
    latest_contracts_total = _column_sum(latest_rows, "CONTRACTS")
    previous_contracts_total = _column_sum(previous_rows, "CONTRACTS")

    return {
        "latest_session": fo.latest_session,
        "previous_session": previous_session,
        "latest_fo_row_count": len(latest_rows),
        "previous_fo_row_count": len(previous_rows),
        "latest_oi_total": latest_oi_total,
        "previous_oi_total": previous_oi_total,
        "oi_delta": _delta(latest_oi_total, previous_oi_total),
        "latest_chg_in_oi_total": latest_chg_in_oi_total,
        "latest_contracts_total": latest_contracts_total,
        "previous_contracts_total": previous_contracts_total,
        "contracts_delta": _delta(latest_contracts_total, previous_contracts_total),
    }


def _now_timestamp() -> str:
    return datetime.now().strftime(TIMESTAMP_FORMAT)


def build_observations(symbol_data: SymbolData) -> dict[str, Any]:
    """Build a deterministic observation dict from a :class:`SymbolData`.

    Returns a dict shaped as::

        {
            "symbol": str,
            "timestamp": "DD:MM:YY HH:MM:SS",
            "lookback_sessions": int,
            "cash": {... latest / previous / delta fields ...},
            "fo":   {... latest / previous / delta fields ...},
        }

    Any numeric value that cannot be derived from the parquet rows is
    returned as ``None`` (no invented fallback). The function never raises
    on missing parquet — it raises only on a malformed ``symbol_data``.
    """
    if not isinstance(symbol_data, SymbolData):
        raise TypeError("symbol_data must be a SymbolData instance")
    return {
        "symbol": symbol_data.symbol,
        "timestamp": _now_timestamp(),
        "lookback_sessions": symbol_data.lookback_sessions,
        "cash": _build_cash(symbol_data.cash),
        "fo": _build_fo(symbol_data.fo),
    }
