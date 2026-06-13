"""Read-only parquet reader for a single symbol.

Reads:

    <install_root>/data/cash/SYMBOL=<SYM>/YEAR=<YYYY>.parquet
    <install_root>/data/fo/SYMBOL=<SYM>/YEAR=<YYYY>.parquet

and returns observable rows for the latest session plus a bounded number of
prior sessions per segment. No comparisons, no derivations, no narrative.
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any

import polars as pl

from . import config
from .models import CashData, FoData, SymbolData

_SESSION_COL = "_d"


def _symbol_dir(root: Path, symbol: str) -> Path:
    return root / f"SYMBOL={symbol.strip().upper()}"


def _shard_paths(sym_dir: Path) -> list[Path]:
    if not sym_dir.is_dir():
        return []
    return sorted(sym_dir.glob("YEAR=*.parquet"))


def _read_frame(sym_dir: Path) -> pl.DataFrame:
    paths = _shard_paths(sym_dir)
    if not paths:
        return pl.DataFrame()
    frames: list[pl.DataFrame] = []
    for fp in paths:
        try:
            frames.append(pl.read_parquet(fp))
        except (OSError, pl.exceptions.PolarsError):
            continue
    if not frames:
        return pl.DataFrame()
    df = pl.concat(frames, how="vertical_relaxed")
    if "DATE" not in df.columns:
        return pl.DataFrame()
    return df.with_columns(
        pl.col("DATE").cast(pl.Utf8).str.slice(0, 10).str.to_date(strict=False).alias(_SESSION_COL)
    ).filter(pl.col(_SESSION_COL).is_not_null())


def _ordered_sessions(df: pl.DataFrame, limit: int) -> list[date]:
    if df.is_empty() or _SESSION_COL not in df.columns:
        return []
    series = df.select(pl.col(_SESSION_COL).unique()).sort(_SESSION_COL, descending=True)[_SESSION_COL]
    return [d for d in series.to_list() if isinstance(d, date)][:limit]


def _to_iso(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return value


def _serialise(row: dict[str, Any]) -> dict[str, Any]:
    return {k: _to_iso(v) for k, v in row.items() if k != _SESSION_COL}


def _rows_on(df: pl.DataFrame, day: date) -> list[dict[str, Any]]:
    if df.is_empty() or _SESSION_COL not in df.columns:
        return []
    chunk = df.filter(pl.col(_SESSION_COL) == day)
    return [_serialise(r) for r in chunk.to_dicts()]


def _build_cash(symbol: str, lookback: int) -> CashData:
    df = _read_frame(_symbol_dir(config.cash_root(), symbol))
    sessions = _ordered_sessions(df, lookback)
    if not sessions:
        return CashData(symbol=symbol)
    latest = sessions[0]
    latest_rows = _rows_on(df, latest)
    latest_row = latest_rows[0] if latest_rows else None
    prev_sessions = [d.isoformat() for d in sessions[1:]]
    prev_rows: list[dict[str, Any]] = []
    for d in sessions[1:]:
        prev_rows.extend(_rows_on(df, d))
    return CashData(
        symbol=symbol,
        latest_session=latest.isoformat(),
        latest_row=latest_row,
        previous_sessions=prev_sessions,
        previous_rows=prev_rows,
    )


def _build_fo(symbol: str, lookback: int) -> FoData:
    df = _read_frame(_symbol_dir(config.fo_root(), symbol))
    sessions = _ordered_sessions(df, lookback)
    if not sessions:
        return FoData(symbol=symbol)
    latest = sessions[0]
    latest_rows = _rows_on(df, latest)
    prev_sessions = [d.isoformat() for d in sessions[1:]]
    prev_rows: list[dict[str, Any]] = []
    for d in sessions[1:]:
        prev_rows.extend(_rows_on(df, d))
    return FoData(
        symbol=symbol,
        latest_session=latest.isoformat(),
        latest_session_rows=latest_rows,
        previous_sessions=prev_sessions,
        previous_session_rows=prev_rows,
    )


def load_symbol_data(symbol: str, lookback_sessions: int = 5) -> SymbolData:
    """Extract observable cash and F&O rows for one symbol.

    Read-only. Returns the latest session plus up to ``lookback_sessions - 1``
    previous sessions per segment, sorted newest first. No comparisons or
    derived metrics are computed.
    """
    sym = symbol.strip().upper() if symbol else ""
    if not sym:
        raise ValueError("symbol required")
    lookback = max(1, int(lookback_sessions))
    cash = _build_cash(sym, lookback)
    fo = _build_fo(sym, lookback)
    return SymbolData(symbol=sym, lookback_sessions=lookback, cash=cash, fo=fo)
