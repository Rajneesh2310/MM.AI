"""Read-only inspection of the F&O parquet schema.

Lists every column (name, dtype, null fraction in the latest session, one
sample value) so the user can choose which ones to expose in the
observation table. No MM file is modified.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    _r = getattr(_s, "reconfigure", None)
    if callable(_r):
        try:
            _r(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import polars as pl

from src.config import fo_root

SYMBOLS_TO_INSPECT = ["RELIANCE", "INFY", "NIFTY"]


def _latest_year_files(symbol: str) -> list[Path]:
    base = fo_root() / f"SYMBOL={symbol}"
    if not base.exists():
        return []
    files = sorted(base.glob("YEAR=*.parquet"))
    return files


def inspect(symbol: str) -> dict:
    files = _latest_year_files(symbol)
    if not files:
        return {"symbol": symbol, "error": "no_fo_parquet"}
    latest_file = files[-1]
    lf = pl.scan_parquet(str(latest_file))
    schema = lf.collect_schema()
    column_info: list[dict] = []
    df = lf.collect()
    if "DATE" in df.columns:
        latest_date = df.select(pl.col("DATE").max()).item()
        latest_rows = df.filter(pl.col("DATE") == latest_date)
    else:
        latest_date = None
        latest_rows = df
    for name in schema.names():
        dtype = str(schema[name])
        sample = None
        null_frac = None
        if name in latest_rows.columns:
            series = latest_rows[name]
            null_frac = round(series.null_count() / max(len(series), 1), 4)
            non_null = series.drop_nulls()
            if len(non_null) > 0:
                value = non_null[0]
                sample = str(value)
        column_info.append(
            {
                "column": name,
                "dtype": dtype,
                "null_fraction_in_latest_session": null_frac,
                "sample_value": sample,
            }
        )
    return {
        "symbol": symbol,
        "file": str(latest_file),
        "latest_session": str(latest_date) if latest_date else None,
        "latest_session_row_count": int(len(latest_rows)),
        "all_year_files": [str(f.name) for f in files],
        "columns": column_info,
    }


def main() -> int:
    out = []
    for sym in SYMBOLS_TO_INSPECT:
        out.append(inspect(sym))
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
