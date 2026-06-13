# MM.AI Workspace Validation Report

Run window: 25:05:26 11:16 (DD:MM:YY HH:MM, IST)
Entry point: `python -m src.workspace <SYMBOL> [--lookback N] [--news-limit N] [--news-timeout S]`
Install root: `C:\Users\DELL\MMMarket`
Pipeline reused (no logic duplicated):

- Observations: `load_symbol_data → build_observations → format_observations`
- News: `fetch_symbol_news`

Sections are always separated by a fixed rule `--------------------------------------------------` and printed in the order **observation block → NEWS block**.

## Commands executed

| # | Command | Purpose | Exit |
|---|---------|---------|------|
| 1 | `python -m src.workspace RELIANCE --lookback 5 --news-limit 3` | Populated cash + F&O + live news | 0 |
| 2 | `python -m src.workspace INFY --news-limit 3` | Populated cash + F&O + live news | 0 |
| 3 | `python -m src.workspace NIFTY --news-limit 3` | F&O only (no cash parquet) + live news | 0 |
| 4 | `python -m src.workspace NONEXISTENT_SYM_123 --news-limit 3` | Missing parquet + (likely) no headlines | 0 |
| 5 | `python -m src.workspace RELIANCE --news-limit 2 --news-timeout 0.001` | Forced news timeout | 0 |

## Symbols tested

- RELIANCE
- INFY
- NIFTY
- NONEXISTENT_SYM_123

## Unit tests

- Suite: `tests/test_workspace.py` — 8 tests
- Full project suite: **45 / 45 passed**
- Linter errors: 0
- Narrative-word guard: `test_no_narrative_words_present` asserts that `bullish`, `bearish`, `recommend`, `buy `, `sell `, `accumulation`, `distribution`, `sentiment`, `we believe`, `likely to` never appear in workspace output

## Observation block generation

| Symbol | Latest cash session | Latest cash CLOSE | Latest F&O session | Latest F&O row count | Latest OI total |
|--------|---------------------|-------------------|---------------------|-----------------------|------------------|
| RELIANCE | 2026-05-20 | 1359.7 | 2026-05-20 | 244 | 118,900,500.0 |
| INFY | 2026-05-20 | 1193.7 | 2026-05-20 | 240 | 67,244,000.0 |
| NIFTY | Not Available | Not Available | 2026-05-20 | 1872 | 396,523,885.0 |
| NONEXISTENT_SYM_123 | Not Available | Not Available | Not Available | 0 | Not Available |

All four runs emitted a complete observation block (CASH + F&O headings, every label / value pair) regardless of data availability.

## News block generation

| Symbol | Headlines returned | Sources observed | NEWS section error token |
|--------|--------------------|------------------|--------------------------|
| RELIANCE | 3 / 3 | The Times of India, Bloomberg.com, AajTak | none |
| INFY | 3 / 3 | Upstox, ChartMill, Equitypandit | none |
| NIFTY | 3 / 3 | The Economic Times, Upstox, LinkedIn | none |
| NONEXISTENT_SYM_123 | 0 | — | `no_headlines` |
| RELIANCE (`--news-timeout 0.001`) | 0 | — | `fetch_failed: _ssl.c:1063: The handshake operation timed out` |

All five runs emitted a NEWS section. Per item the fields are exactly `Source:`, `Headline:`, `URL:`; for empty / error cases each field renders as `Not Available`.

## Timestamp validation

- Required pattern: `[DD:MM:YY HH:MM:SS]`
- Regex anchor: `\[\d{2}:\d{2}:\d{2} \d{2}:\d{2}:\d{2}\]`
- Both sections (observation header + NEWS header) carry an independent timestamp matching this pattern.
- Observed first-line timestamps: `[25:05:26 11:16:33]`, `[25:05:26 11:16:35]`, `[25:05:26 11:16:37]`, `[25:05:26 11:16:39]`, `[25:05:26 11:16:41]`.
- NEWS-section timestamps reflect render time (independent fetch instant) and may differ from the observation timestamp.

## Null handling validation

| Case | Behaviour |
|------|-----------|
| Cash parquet absent (NIFTY, NONEXISTENT_SYM_123) | Every cash label renders as `Not Available`; observation block still complete |
| F&O parquet absent (NONEXISTENT_SYM_123) | Every F&O numeric renders as `Not Available`; row counts render as integer `0` |
| Source delivery columns null (RELIANCE, INFY) | All delivery cash fields render as `Not Available` (deterministic — source parquet carries nulls) |
| News empty (NONEXISTENT_SYM_123, forced-timeout RELIANCE) | NEWS section renders one block of `Source: Not Available`, `Headline: Not Available`, `URL: Not Available`, followed by the separator |
| Source field missing on an item | `Source:` value renders as `Not Available` |

## Timeout / error handling validation

| Case | Output | Exit code |
|------|--------|-----------|
| Forced news timeout (`--news-timeout 0.001`) | Full observation block rendered first; NEWS section shows `ERROR: fetch_failed: _ssl.c:1063: ...` + `Not Available` placeholders | 0 |
| Missing parquet + missing headlines (NONEXISTENT_SYM_123) | Observation block fully `Not Available`; NEWS section `ERROR: no_headlines` + `Not Available` placeholders | 0 |
| Blank symbol (`python -m src.workspace "  "`) | stderr `error: blank symbol`; no output | 2 |
| Invalid lookback (`--lookback 0`) | stderr `error: --lookback must be >= 1`; no output | 2 |
| Invalid news-limit (`--news-limit 0`) | stderr `error: --news-limit must be >= 1`; no output | 2 |
| Invalid news-timeout (`--news-timeout 0`) | stderr `error: --news-timeout must be > 0`; no output | 2 |

Mocked-network unit-test matrix (already validated under `tests/test_news_fetcher.py`) is reused — the workspace test suite mocks `src.workspace.fetch_symbol_news` to assert section ordering, layout, and the forbidden-narrative guard independently of the live network.

## Section separation guarantees

- Observation block is emitted in full before the separator rule.
- Separator rule (`-` × 50) appears exactly once between observation and news sections.
- A second separator rule appears at the end of each news item (and as a closing rule when the news list is empty).
- News data is never merged into observation values; observation values never reference news content. Verified by `test_two_sections_separated_by_rule`, `test_news_section_after_separator`, and `test_no_narrative_words_present`.

## Warnings / errors

- INFY observation block carried `Close Delta: -3.2` (deterministic rounding of the float-arithmetic artefact `-3.2000000000000455` at format time only; underlying observation value unchanged).
- RELIANCE / INFY cash delivery columns null in source parquet → all delivery fields rendered as `Not Available`. No exceptions.
- NIFTY has no cash parquet on disk → entire CASH block rendered as `Not Available`. No exceptions.
- NONEXISTENT_SYM_123 has no parquet at all → full observation block of `Not Available` plus NEWS error token `no_headlines`. No exceptions.
- Forced `--news-timeout 0.001` produced the documented token `fetch_failed: _ssl.c:1063: The handshake operation timed out`; observation block was still rendered first. No exceptions.
- No interpretation, summary, sentiment, classification, recommendation, prediction, or AI narrative produced for any symbol.
