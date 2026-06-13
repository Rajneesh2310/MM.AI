# MM.AI Text Formatter Validation Report

Run timestamp: 25:05:26 10:50:14 (DD:MM:YY HH:MM:SS, render-time)
Install root: `C:\Users\DELL\MMMarket`
Pipeline: `load_symbol_data` → `build_observations` → `format_observations`
Formatter: `src.text_formatter.format_observations`

## Symbols tested

- RELIANCE
- INFY
- NIFTY

## Unit tests

- Suite: `tests/test_text_formatter.py`
- Result: 10 / 10 passed
- Full project suite (`tests/`): 25 / 25 passed
- Linter errors: 0

## Timestamp format validation

- Required pattern: `DD:MM:YY HH:MM:SS`
- Regex anchor: `^\[\d{2}:\d{2}:\d{2} \d{2}:\d{2}:\d{2}\]$`
- RELIANCE first line: `[25:05:26 10:50:14]` — matches
- INFY first line: `[25:05:26 10:50:14]` — matches
- NIFTY first line: `[25:05:26 10:50:15]` — matches
- Render-time vs. input-timestamp: render-time always used (verified by `test_timestamp_is_render_time_not_input_timestamp`)

## Numeric formatting validation

| Source value | Rendered as | Notes |
|--------------|-------------|-------|
| `1359.7` | `1359.7` | unchanged |
| `13248515.0` | `13248515.0` | unchanged |
| `37.0` | `37.0` | unchanged |
| `-8416986.0` | `-8416986.0` | unchanged |
| `-3.2000000000000455` (INFY close delta) | `-3.2` | float artefact rounded to 6 fractional digits |
| `244` (row count, int) | `244` | int rendered without `.0` |
| `-317478395.0` | `-317478395.0` | unchanged |
| Non-numeric (`"garbage"`) | `Not Available` | invalid coerced to NA |
| NaN / Inf | `Not Available` | rejected by `_format_float` |

Underlying observation values were **not** mutated; rounding occurs at render time only.

## Null handling validation

- Null token used: `Not Available`
- RELIANCE: 6 `Not Available` lines (all delivery cash fields)
- INFY: 6 `Not Available` lines (all delivery cash fields)
- NIFTY: 14 `Not Available` lines (entire cash block — no cash parquet on disk)
- Missing top-level sections (e.g. supply `{"symbol": "RELIANCE"}` only): cash + F&O still emitted with every field rendering as `Not Available`

## Output structure validation

- First line: timestamp inside `[...]`
- Blank line
- `SYMBOL: <SYM>` line
- Blank line
- `CASH` header, blank line, then 14 label/value pairs
- `F&O` header, blank line, then 11 label/value pairs
- Each field uses two lines: `<Label>:` then the value, separated from the next field by a blank line
- Trailing newline: single (`text.endswith("\n")` and not `"\n\n"`)

## Per-symbol render result

| Symbol | Formatter exit | Output bytes | Not Available count | Notes |
|--------|----------------|--------------|---------------------|-------|
| RELIANCE | success | ~975 chars | 6 | cash delivery fields null on source parquet |
| INFY | success | ~975 chars | 6 | cash delivery fields null on source parquet; `close_delta` artefact `-3.2000000000000455` rendered as `-3.2` |
| NIFTY | success | ~975 chars | 14 | cash parquet absent on source install |

## Rendered text — verbatim samples

### RELIANCE (head)

```
[25:05:26 10:50:14]

SYMBOL: RELIANCE

CASH

Latest Session:
2026-05-20

Previous Session:
2026-05-19

Latest Close:
1359.7

Previous Close:
1322.7

Close Delta:
37.0
```

### INFY (artefact-rounding excerpt)

```
Previous Close:
1196.9

Close Delta:
-3.2
```

### NIFTY (cash-absent excerpt)

```
CASH

Latest Session:
Not Available

Previous Session:
Not Available

Latest Close:
Not Available
```

## Warnings / errors

- No exceptions raised across the three runs.
- No interpretation, narrative, prediction, classification, or recommendation produced.
- Delivery columns for RELIANCE and INFY rendered as `Not Available` because the source parquet carries nulls in those columns.
- NIFTY cash block rendered entirely as `Not Available` because no cash parquet exists for NIFTY on this install.
- Observation `close_delta = -3.2000000000000455` for INFY rendered as `-3.2` (deterministic 6-digit fractional rounding at format time only — the observation dict was not modified).
