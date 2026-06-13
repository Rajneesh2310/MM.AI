# MM.AI News Fetcher Validation Report

Run window: 25:05:26 11:11 — 11:12 (DD:MM:YY HH:MM, IST)
Entry point: `python -m src.news_fetcher <SYMBOL> [--limit N] [--timeout S]`
Feed source: Google News public RSS (`https://news.google.com/rss/search?q=...&hl=en-IN&gl=IN&ceid=IN:en`)
Network transport: stdlib `urllib.request` with UTF-8 stdout reconfiguration
Persistence: none (no cache, no file, no DB, no article body)

## Symbols tested

- RELIANCE
- INFY
- NIFTY

Negative cases also exercised: blank symbol, very-low timeout, plus full mocked-network unit-test matrix.

## Unit tests

- Suite: `tests/test_news_fetcher.py` — 12 tests
- Full project suite: 37 / 37 passed
- Linter errors: 0

## Live-fetch results

### RELIANCE — `python -m src.news_fetcher RELIANCE --limit 5`

- Timestamp: `[25:05:26 11:12:24]`
- Query URL: `https://news.google.com/rss/search?q=RELIANCE&hl=en-IN&gl=IN&ceid=IN:en`
- Headlines fetched: 5 / 5 requested
- Sources observed: `The Times of India`, `Bloomberg.com`, `AajTak`, `Hortidaily`, `Zee Business`
- URL count: 5 (all `https://news.google.com/rss/articles/...`)
- Error: none
- Exit code: 0
- Notes: one headline contains a non-ASCII rupee symbol (`₹`) and Devanagari script — rendered correctly with UTF-8 stdout.

### INFY — `python -m src.news_fetcher INFY --limit 5`

- Timestamp: `[25:05:26 11:12:35]`
- Query URL: `https://news.google.com/rss/search?q=INFY&hl=en-IN&gl=IN&ceid=IN:en`
- Headlines fetched: 5 / 5 requested
- Sources observed: `Upstox`, `ChartMill`, `Equitypandit`, `Mint`, `The Economic Times`
- URL count: 5
- Error: none
- Exit code: 0
- Notes: rupee symbol present in headline #1 — rendered correctly.

### NIFTY — `python -m src.news_fetcher NIFTY --limit 5`

- Timestamp: `[25:05:26 11:11:56]`
- Query URL: `https://news.google.com/rss/search?q=NIFTY&hl=en-IN&gl=IN&ceid=IN:en`
- Headlines fetched: 5 / 5 requested
- Sources observed: `The Economic Times`, `Upstox`, `LinkedIn`, `Mint`, `India Today`
- URL count: 5
- Error: none
- Exit code: 0
- Notes: headlines reference index levels in raw text only; no interpretation, no sentiment is produced by MM.AI.

### Aggregate counts

| Metric | RELIANCE | INFY | NIFTY |
|--------|----------|------|-------|
| Headlines requested | 5 | 5 | 5 |
| Headlines returned | 5 | 5 | 5 |
| Distinct sources observed | 5 | 5 | 5 |
| URLs returned | 5 | 5 | 5 |
| Errors raised | 0 | 0 | 0 |

## Timestamp validation

- Required pattern: `DD:MM:YY HH:MM:SS`
- Regex anchor: `^\[\d{2}:\d{2}:\d{2} \d{2}:\d{2}:\d{2}\]$`
- All three live runs emit a first line matching this pattern (`[25:05:26 11:12:24]`, `[25:05:26 11:12:35]`, `[25:05:26 11:11:56]`).
- Each `NewsItem.timestamp` field equals the parent `NewsResult.timestamp` (verified by `test_timestamp_format_matches_spec`).

## Error / timeout handling validation

| Case | Command | Output | Exit code |
|------|---------|--------|-----------|
| Blank symbol | `python -m src.news_fetcher "  "` | `ERROR: blank_symbol`, `COUNT: 0`, `SYMBOL: Not Available`, `QUERY URL: Not Available` | 1 |
| Forced timeout | `python -m src.news_fetcher RELIANCE --timeout 0.001` | `ERROR: fetch_failed: _ssl.c:1063: The handshake operation timed out`, `COUNT: 0`, query URL printed | 1 |
| HTTP error (mocked) | unit test `test_http_error_returns_http_token` | `error == "http_503"` | n/a |
| URL error (mocked) | unit test `test_url_error_returns_fetch_failed_token` | `error.startswith("fetch_failed")` | n/a |
| Malformed XML (mocked) | unit test `test_malformed_xml_returns_parse_error` | `error.startswith("malformed_xml")` | n/a |
| Empty channel (mocked) | unit test `test_no_items_returns_no_headlines_error` | `error == "no_headlines"` | n/a |
| `socket.timeout` (mocked) | unit test `test_timeout_returns_timeout_error` | `error == "timeout"` | n/a |

All error paths return a deterministic factual `NewsResult` with `items=[]`, `count=0`, and a short token in `error`. No traceback reaches the user via the CLI.

## Output contract (per `NewsItem`)

- `headline` — exact title string from RSS, including source suffix as published
- `source` — `<source>` element text, or `None` if the feed omits it
- `url` — RSS `<link>` value (article URL; not fetched, not stored)
- `timestamp` — MM.AI fetch/render time in `DD:MM:YY HH:MM:SS`

No article body, summary, sentiment, classification, recommendation, or AI narrative is generated.

## Warnings / errors

- Initial CLI runs against RELIANCE and INFY surfaced a Windows console `cp1252` encode failure when printing non-ASCII characters in headlines (`₹`, Devanagari). Remediated by reconfiguring `sys.stdout` / `sys.stderr` to UTF-8 in `main()`; the `NewsItem` data itself was never altered.
- Forced low timeout (`--timeout 0.001`) produced the documented `fetch_failed: _ssl.c:...` token via `URLError`; no exception bubbled.
- NIFTY query terms are intentionally minimal (`q=NIFTY`); the returned headlines are public, third-party aggregated, and used here only to validate the fetcher contract — MM.AI applies no interpretation.
- No interpretation, sentiment, causation, recommendation, or hidden-intent inference produced for any symbol.

## Files

- Code (read-only, in-memory only): `src/news_fetcher.py`, `src/news_models.py`
- Tests (mocked network): `tests/test_news_fetcher.py`
- Report: this file
- No persistence, no cache, no article archive created or written.
