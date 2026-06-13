# MM.AI Desktop Workspace UI — Validation Report

Generated: 25:05:26 11:28:00 (local)
Scope: PySide6 single-window UI over the validated MM.AI backend pipeline.
Pipeline driven on every load: `load_symbol_data` → `build_observations` → `format_observations` → `fetch_symbol_news`.

---

## 1. Files Delivered (inside `MM.AI/`)

| File | Role |
| --- | --- |
| `src/app.py` | Entry point — creates `QApplication`, shows the workspace window. |
| `src/workspace_window.py` | Controller — owns `WorkspaceController`, the synchronous `run_pipeline` helper, the news-HTML renderer, and a background `QThread` worker. |
| `src/ui/main_window.py` | `MainWindow` — pure-layout `QMainWindow` (header, search row, vertical splitter, status bar). |
| `src/ui/__init__.py` | Package marker. |
| `tests/test_ui_workspace.py` | Headless pytest suite (`QT_QPA_PLATFORM=offscreen`). |
| `tests/_ui_validation_run.py` | Headless live validation runner used for this report. |

No MM core file was modified. No new persistence, cache, or storage layer was introduced. PySide6 was added to `requirements.txt` (the existing MM venv already ships `PySide6==6.11.1`).

---

## 2. Window & Layout Conformance

| Spec | Status |
| --- | --- |
| Single window only | OK |
| Initial size 1200 × 800 | OK (`window.size() == (1200, 800)`) |
| Resizable (min 900 × 600) | OK |
| Header height ~60 px | OK (`setFixedHeight(60)`) |
| Header LEFT: "MM.AI Workspace" title | OK |
| Header RIGHT: live `[DD:MM:YY HH:MM:SS]` clock + status label | OK (1 s `QTimer`) |
| Symbol input with placeholder "Enter Symbol (Example: RELIANCE)" | OK |
| Lookback spin (default 5, range 1–365) | OK |
| News Limit spin (default 5, range 1–50) | OK |
| `Load Workspace` button | OK |
| OBSERVATIONS read-only multiline area (`QPlainTextEdit`, no wrap, monospace) | OK |
| NEWS scrollable read-only area (`QTextBrowser`, `setOpenExternalLinks(True)`) | OK |
| Bottom `QStatusBar` showing symbol / success / failure / runtime errors | OK |
| Style: no gradients, no flashy colors, neutral greys | OK |
| No charts, watchlists, dashboards, recommendations, prediction, AI chat, LLM | OK |

---

## 3. Symbols Tested

`RELIANCE`, `INFY`, `NIFTY`, `NONEXISTENT_SYM_123`.

All four were driven through the exact `run_pipeline` function the UI worker calls, then pushed into a real `MainWindow` instance via `set_observation_text` / `set_news_html`. The MM data root used was the default resolved root (`C:\Users\DELL\MMMarket`, with `cash/` and `fo/` present).

### 3.1 RELIANCE — load success

| Check | Value |
| --- | --- |
| UI load success | OK |
| Observation block rendered | OK (813 chars) |
| `SYMBOL:` line present | RELIANCE |
| `[DD:MM:YY HH:MM:SS]` header timestamp | OK |
| `CASH` header / `F&O` header | OK / OK |
| `Latest Session` (cash) | `2026-05-20` |
| `Latest Close` | `1359.7` |
| `Close Delta` | `37.0` |
| `Latest OI Total` | `118900500.0` |
| News count | 5 |
| Clickable URL anchors in NEWS HTML | 5 |
| News error | None |
| First source / headline | `The Times of India` / `Market recap: 6 of top-10 most-valued firms add Rs 74,111 crore; Reliance biggest winner - The Times of India` |

### 3.2 INFY — load success, float artefact rounded

| Check | Value |
| --- | --- |
| UI load success | OK |
| Observation block rendered | OK (809 chars) |
| `SYMBOL:` | INFY |
| `Latest Session` (cash) | `2026-05-20` |
| `Latest Close` | `1193.7` |
| `Close Delta` | `-3.2` (raw IEEE-754 artefact `-3.2000000000000455` rounded for display only) |
| `Latest OI Total` | `67244000.0` |
| News count | 5 |
| Clickable URL anchors in NEWS HTML | 5 |
| First source / headline | `Upstox` / `Infosys' ₹18,000 crore share buyback opens: Five key things to know - Upstox` (Unicode `₹` rendered safely via `QTextBrowser`; no `UnicodeEncodeError`) |

### 3.3 NIFTY — partial data (cash absent), F&O present

| Check | Value |
| --- | --- |
| UI load success | OK (no crash) |
| Observation block rendered | OK (863 chars) |
| `SYMBOL:` | NIFTY |
| Cash `Latest Session` | `Not Available` |
| Cash `Latest Close` | `Not Available` |
| Cash `Close Delta` | `Not Available` |
| `Latest OI Total` (F&O) | `396523885.0` |
| News count | 5 |
| Clickable URL anchors in NEWS HTML | 5 |
| First source | `NDTV` |

### 3.4 NONEXISTENT_SYM_123 — graceful empty path

| Check | Value |
| --- | --- |
| UI load success (no crash) | OK |
| Observation block rendered | OK (891 chars, all numeric fields `Not Available`) |
| `SYMBOL:` | NONEXISTENT_SYM_123 |
| Cash `Latest Session` / `Latest Close` / `Close Delta` | `Not Available` / `Not Available` / `Not Available` |
| `Latest OI Total` | `Not Available` |
| News count | 0 |
| News error | `no_headlines` |
| News block | `Source: Not Available`, `Headline: Not Available`, `URL: Not Available` + `ERROR: no_headlines` line — no anchors emitted |
| Anchors in NEWS HTML | 0 |

---

## 4. Observation Rendering Validation

For every loaded symbol the OBSERVATIONS panel contained, in order, and exactly as produced by `format_observations()` (no reformatting, no colourisation, no AI injection):

```
[DD:MM:YY HH:MM:SS]

SYMBOL: <symbol>

CASH

Latest Session: ...
Previous Session: ...
Latest Close: ...
Previous Close: ...
Close Delta: ...
Latest Volume: ...
Previous Volume: ...
Volume Delta: ...
Latest Delivery Qty: ...
Previous Delivery Qty: ...
Delivery Qty Delta: ...
Latest Delivery Percent: ...
Previous Delivery Percent: ...
Delivery Percent Delta: ...

F&O

Latest Session: ...
Previous Session: ...
Latest F&O Row Count: ...
Previous F&O Row Count: ...
Latest OI Total: ...
Previous OI Total: ...
OI Delta: ...
Latest Chg In OI Total: ...
Latest Contracts Total: ...
Previous Contracts Total: ...
Contracts Delta: ...
```

Confirmed for all four symbols:

- Timestamp header matches `^\[\d{2}:\d{2}:\d{2} \d{2}:\d{2}:\d{2}\]$`.
- Null/missing values render as `Not Available` (no `None`, no empty value, no narrative).
- Numeric values are emitted as plain decimal strings; no thousands separators, no colourisation, no qualitative labels.
- The text shown in the UI equals the bytes returned by `format_observations()` (verified via `MainWindow.observation_text()`).

---

## 5. News Rendering Validation

News items in the UI are rendered through `_format_news_html()` into a `QTextBrowser` with `setOpenExternalLinks(True)`.

Each non-empty item produces a block of:

```
Source:
<source or "Not Available">

Headline:
<headline or "Not Available">

URL:
<a href="...">...</a>

--------------------------------------------------
```

Verified properties:

| Property | Result |
| --- | --- |
| Items rendered in the order returned by `fetch_symbol_news` (no reordering) | OK |
| Per-item separator `--------------------------------------------------` (50 dashes) | OK |
| URL emitted as `<a href="...">...</a>` | OK |
| `setOpenExternalLinks(True)` so anchors launch via the OS default browser | OK |
| Anchor count equals `news_count` (RELIANCE 5/5, INFY 5/5, NIFTY 5/5, NONEXISTENT 0/0) | OK |
| Empty result renders `Not Available` placeholders, **no** anchors | OK |
| News header line contains `SYMBOL:`, `COUNT:`, optional `ERROR:` | OK |
| No sentiment, no classification, no summarisation, no merging into observations | OK |
| HTML escaping for headline/source/URL (`<script>` payload rendered as `&lt;script&gt;` in tests) | OK |
| Unicode characters (e.g. `₹`) preserved in `QTextBrowser` | OK |

---

## 6. Clickable URL Validation

- `QTextBrowser.openExternalLinks` is enabled, so anchors fire `QDesktopServices.openUrl(...)` against the OS default browser without spawning an in-window browser (no browser embedding).
- Headless test `test_news_html_contains_clickable_anchor_per_item` asserts one `<a href="...">` per news item.
- Live runs produced 5 anchors for RELIANCE / INFY / NIFTY and 0 anchors for `NONEXISTENT_SYM_123` (empty news), matching the spec ("URLs must be clickable" applies only to real items; missing items render as `Not Available`).
- First anchor href captured per symbol (truncated):
  - RELIANCE → `https://news.google.com/rss/articles/CBMihAJBVV95...`
  - INFY → `https://news.google.com/rss/articles/CBMiwAFBVV95...`
  - NIFTY → `https://news.google.com/rss/articles/CBMi-AFBVV95...`
  - NONEXISTENT_SYM_123 → (no anchors)

---

## 7. Timeout / Error Handling Validation

| Scenario | UI behaviour |
| --- | --- |
| Blank symbol submitted | Pipeline not invoked; status bar shows `error: blank symbol`; load button re-enabled. Verified by `test_controller_rejects_blank_symbol`. |
| Lookback = 0 (range relaxed for test) | Pipeline not invoked; status bar shows `error: lookback must be >= 1`. Verified by `test_controller_rejects_zero_lookback`. |
| Cash parquet absent (NIFTY) | Observation panel renders with cash fields = `Not Available`; F&O fields populated. No crash, no traceback in UI. |
| Symbol unknown to MM (`NONEXISTENT_SYM_123`) | All observation fields = `Not Available`; news section renders empty-item block with `ERROR: no_headlines`. Status bar reads `loaded NONEXISTENT_SYM_123 — news error: no_headlines`. |
| News HTTP timeout (`news_timeout=0.001` mock) | Observation panel renders normally; news block carries `ERROR: timeout` and zero anchors. Verified by `test_pipeline_news_timeout`. |
| Malformed RSS / network error | `fetch_symbol_news` returns a `NewsResult` with `count=0` and `error=<reason>`; UI renders the `Not Available` empty-news block with the `ERROR:` line and zero anchors. |
| Unexpected exception in worker | `_PipelineWorker.failed` signal fires; status bar shows `error: <Type>: <message>`; UI remains interactive, load button re-enabled. |

The UI thread is never blocked: every load runs in a `QThread` worker, so a slow news fetch leaves the search bar, status bar and clock responsive.

---

## 8. Test & Headless Run Results

```
pytest tests/test_ui_workspace.py    →  12 passed
pytest tests/                        →  57 passed
python tests/_ui_validation_run.py   →  exit 0  (4 symbols, real MM data + live RSS)
python -m src.app (offscreen, 150 ms QTimer quit)  →  exit 0, window visible
```

Tests cover: default sizes & placeholders, signal emission, view setters, news HTML structure (anchors / empty / escaping), pipeline runs for RELIANCE-like / NIFTY-like / non-existent / timeout, controller guards for blank symbol & invalid lookback.

---

## 9. Warnings / Notes

- The Windows `cp1252` console encoding cannot encode characters like `₹` that appear in live RSS titles. The validation runner reconfigures `sys.stdout`/`sys.stderr` to UTF-8 (same fix already shipped in `news_fetcher.py`). The UI itself is unaffected because `QTextBrowser.setHtml` does not go through `sys.stdout`.
- Anchors point to Google News redirect URLs (`news.google.com/rss/articles/...`) — this is the canonical link returned by the upstream RSS feed and is preserved verbatim. No URL rewriting is performed.
- F&O `Latest OI Total = 0.0` appearing in any future symbol still renders as `0.0` (a deterministic numeric fact); only genuine `None`/parse-failure values render as `Not Available`.
- No corporate-action adjustment, no derived analytic, no merging of news into observations.
