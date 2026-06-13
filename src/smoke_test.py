"""MM.AI CLI smoke test — end-to-end proof that the reader can load MM parquet.

Usage::

    python -m src.smoke_test RELIANCE
    python -m src.smoke_test RELIANCE --lookback 5

Prints only deterministic factual rows extracted from MM parquet. No
comparisons, averages, narratives, predictions, interpretation, or formatting
frameworks.

Exit codes:
    0  cash and/or F&O parquet read successfully for the symbol
    1  symbol resolved but neither cash nor F&O parquet was found
    2  invalid arguments (e.g. blank symbol)
    3  I/O failure while reading parquet shards
    4  unexpected failure (printed factually to stderr)
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from typing import Any

from . import config
from .models import SymbolData
from .symbol_reader import load_symbol_data


def _timestamp() -> str:
    return datetime.now().strftime("[%d:%m:%y %H:%M:%S]")


def _get(row: dict[str, Any] | None, key: str) -> Any:
    if not row:
        return None
    return row.get(key)


def _count_non_null(rows: list[dict[str, Any]], key: str) -> int:
    return sum(1 for r in rows if r.get(key) is not None)


def _fmt(value: Any) -> str:
    if value is None:
        return "n/a"
    return str(value)


def _print_header(symbol: str, lookback: int) -> None:
    print(_timestamp())
    print()
    print(f"SYMBOL: {symbol}")
    print(f"LOOKBACK_SESSIONS: {lookback}")
    print()


def _print_paths() -> None:
    print("PATHS")
    print(f"- install root: {config.install_root()}")
    print(f"- cash root: {config.cash_root()}")
    print(f"- fo root: {config.fo_root()}")
    print()


def _print_cash(data: SymbolData) -> None:
    cash = data.cash
    rows_loaded = (1 if cash.latest_row else 0) + len(cash.previous_rows)
    print("CASH")
    print(f"- latest session date: {_fmt(cash.latest_session)}")
    print(f"- row count loaded: {rows_loaded}")
    print(f"- previous sessions loaded: {len(cash.previous_sessions)}")
    print(f"- latest CLOSE: {_fmt(_get(cash.latest_row, 'CLOSE'))}")
    print(f"- latest VOLUME: {_fmt(_get(cash.latest_row, 'VOLUME'))}")
    print()


def _print_fo(data: SymbolData) -> None:
    fo = data.fo
    total = len(fo.latest_session_rows) + len(fo.previous_session_rows)
    oi_available = _count_non_null(fo.latest_session_rows, "OPEN_INT")
    print("F&O")
    print(f"- latest session date: {_fmt(fo.latest_session)}")
    print(f"- total F&O rows loaded: {total}")
    print(f"- latest session row count: {len(fo.latest_session_rows)}")
    print(f"- previous sessions loaded: {len(fo.previous_sessions)}")
    print(f"- latest OPEN_INT values available count: {oi_available}")
    print()


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="smoke_test",
        description="MM.AI parquet reader smoke test — read-only, factual output only.",
    )
    parser.add_argument("symbol", help="Symbol to load, e.g. RELIANCE")
    parser.add_argument(
        "--lookback",
        type=int,
        default=5,
        help="Number of sessions per segment to load (default: 5).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    raw_symbol = (args.symbol or "").strip()
    if not raw_symbol:
        print("error: blank symbol", file=sys.stderr)
        return 2
    if args.lookback < 1:
        print("error: --lookback must be >= 1", file=sys.stderr)
        return 2

    try:
        data = load_symbol_data(raw_symbol, lookback_sessions=args.lookback)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"error: I/O failure reading parquet: {exc}", file=sys.stderr)
        return 3
    except Exception as exc:  # noqa: BLE001 — factual fallback for malformed parquet
        print(f"error: unexpected failure: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 4

    _print_header(data.symbol, data.lookback_sessions)
    _print_paths()
    _print_cash(data)
    _print_fo(data)

    if data.cash.latest_session is None and data.fo.latest_session is None:
        print(f"note: no cash or F&O parquet found for {data.symbol}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
