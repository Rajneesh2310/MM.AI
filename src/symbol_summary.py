"""MM.AI deterministic symbol summary CLI.

Single command that runs the existing MM.AI pipeline end-to-end::

    load_symbol_data → build_observations → format_observations

and prints the formatter output to stdout. No additional formatting,
colours, banners, tables, narratives, or interpretation are introduced.

Usage::

    python -m src.symbol_summary RELIANCE
    python -m src.symbol_summary RELIANCE --lookback 5

Exit codes:
    0  pipeline produced formatted output (some fields may be ``Not Available``)
    2  invalid arguments (blank symbol or non-positive lookback)
    3  I/O failure reading parquet shards
    4  unexpected failure (factual message printed to stderr)
"""

from __future__ import annotations

import argparse
import sys

from .observation_builder import build_observations
from .symbol_reader import load_symbol_data
from .text_formatter import format_observations


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="symbol_summary",
        description="MM.AI deterministic per-symbol summary (read-only).",
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
    try:
        args = _parse_args(argv)
    except SystemExit as exc:
        return int(exc.code) if exc.code is not None else 2

    raw_symbol = (args.symbol or "").strip()
    if not raw_symbol:
        print("error: blank symbol", file=sys.stderr)
        return 2
    if args.lookback < 1:
        print("error: --lookback must be >= 1", file=sys.stderr)
        return 2

    try:
        symbol_data = load_symbol_data(raw_symbol, lookback_sessions=args.lookback)
        observations = build_observations(symbol_data)
        text = format_observations(observations)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"error: I/O failure reading parquet: {exc}", file=sys.stderr)
        return 3
    except Exception as exc:  # noqa: BLE001 — factual fallback for malformed parquet
        print(f"error: unexpected failure: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 4

    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
