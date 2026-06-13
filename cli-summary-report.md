# MM.AI CLI Summary Validation Report

Run timestamp: 25:05:26 10:53 (DD:MM:YY HH:MM, local IST)
Install root: `C:\Users\DELL\MMMarket`
Pipeline executed by CLI: `load_symbol_data → build_observations → format_observations`
Entry point: `python -m src.symbol_summary <SYMBOL> [--lookback N]`

## Commands executed

| # | Command | Purpose | Exit |
|---|---------|---------|------|
| 1 | `python -m src.symbol_summary RELIANCE` | Default lookback (5) on populated symbol | 0 |
| 2 | `python -m src.symbol_summary INFY --lookback 5` | Explicit lookback on populated symbol | 0 |
| 3 | `python -m src.symbol_summary NIFTY --lookback 3` | Symbol with F&O only (no cash parquet) | 0 |
| 4 | `python -m src.symbol_summary NONEXISTENT_SYM_123` | Symbol with no parquet at all | 0 |
| 5 | `python -m src.symbol_summary RELIANCE --lookback 0` | Invalid lookback | 2 |
| 6 | `python -m src.symbol_summary "  "` | Blank symbol | 2 |

Full project test suite re-run: **25 / 25 passed**, lints clean.

## Symbols tested

- RELIANCE
- INFY
- NIFTY
- NONEXISTENT_SYM_123 (negative case)

## Output generation per symbol

| Symbol | Output produced | Exit | First-line timestamp |
|--------|-----------------|------|----------------------|
| RELIANCE | yes — full CASH + F&O block | 0 | `[25:05:26 10:53:20]` |
| INFY | yes — full CASH + F&O block (close delta artefact rendered as `-3.2`) | 0 | `[25:05:26 10:53:21]` |
| NIFTY | yes — CASH block all `Not Available`, F&O block populated | 0 | `[25:05:26 10:53:23]` |
| NONEXISTENT_SYM_123 | yes — every observable field `Not Available`; F&O row counts `0` | 0 | `[25:05:26 10:53:25]` |

## Timestamp validation

- Required pattern: `[DD:MM:YY HH:MM:SS]`
- Regex anchor: `^\[\d{2}:\d{2}:\d{2} \d{2}:\d{2}:\d{2}\]$`
- All four successful runs emit a first line matching this pattern.
- Timestamps reflect MM.AI render time (formatter generates them at format step).

## Null handling validation

| Symbol | `Not Available` count in output | Source |
|--------|----------------------------------|--------|
| RELIANCE | 6 | All delivery cash fields null on source parquet |
| INFY | 6 | All delivery cash fields null on source parquet |
| NIFTY | 14 | Entire cash block — no cash parquet for NIFTY on this install |
| NONEXISTENT_SYM_123 | 23 | No cash and no F&O parquet — every numeric field rendered as `Not Available`; F&O row counts rendered as integer `0` |

In every case the CLI produced a complete two-section block (`CASH`, `F&O`) with one `<Label>:` / `<value>` pair per field. No exceptions reached the user.

## Error-handling validation

| Case | Command | stderr message | Exit code |
|------|---------|----------------|-----------|
| Blank symbol | `python -m src.symbol_summary "  "` | `error: blank symbol` | 2 |
| Invalid lookback | `python -m src.symbol_summary RELIANCE --lookback 0` | `error: --lookback must be >= 1` | 2 |
| Missing parquet | `python -m src.symbol_summary NONEXISTENT_SYM_123` | none — graceful empty rendering | 0 |

Exit-code contract (as implemented):

- `0` — pipeline produced formatted output (some fields may be `Not Available`).
- `2` — invalid arguments.
- `3` — I/O failure reading parquet (not triggered in this validation run).
- `4` — unexpected failure (not triggered in this validation run).

## Pipeline integrity

- `symbol_summary.py` calls existing modules only — no logic duplicated:
  - `from .symbol_reader import load_symbol_data`
  - `from .observation_builder import build_observations`
  - `from .text_formatter import format_observations`
- CLI emits exactly the formatter output; no additional banners, colours, tables, narratives, or AI-style language are added.

## Warnings / errors

- No exceptions raised during any of the six runs.
- Cash delivery columns null in source parquet for RELIANCE and INFY → all delivery fields rendered as `Not Available`.
- NIFTY cash parquet absent → entire CASH block rendered as `Not Available`.
- NONEXISTENT_SYM_123 has no parquet on disk → fully `Not Available` block with row counts at integer `0`; exit code 0 (the CLI treats absence as a valid, fully-null observation rather than an error).
- No interpretation, narrative, prediction, recommendation, or hidden-intent inference was produced.
