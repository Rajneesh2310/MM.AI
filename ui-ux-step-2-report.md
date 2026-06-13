# MM.AI Desktop UI — UX Step 2 Report

Step focus: information-density refactor on top of UX Step 1's dark theme.

The seven user-driven changes:

1. Row-count rows removed from the observation panel.
2. Observations now render as a side-by-side comparison table
   (`Parameter | Previous | Latest | Δ`).
3. News block is a continuously-scrolling ticker — no manual scrollbar; the
   crawl pauses on hover so URLs remain clickable.
4. Screen never shows a manual scrollbar for the single-symbol case
   (vertical or horizontal).
5. `Load Workspace` button removed — Enter (in any input) triggers the load.
6. `Lookback` and `News` spin boxes are now compact 2-digit fields with no
   step arrows, capped at `99`.
7. Comma-separated multi-symbol input renders side-by-side; the observation
   table acquires a horizontal scrollbar when the symbol set overflows.

Backend pipeline (`symbol_reader`, `observation_builder`, `text_formatter`,
`news_fetcher`) is byte-identical to UX Step 1. MM core and parquet files
were not touched.

---

## 1. Files Modified / Added (inside `MM.AI/`)

| File | Change |
| --- | --- |
| `src/observation_table.py` | **New.** `render_observation_html(observations)` builds the HTML comparison table. Two sections — `CASH` (Session, Close, Volume, Delivery Qty, Delivery %) and `F&O` (Session, OI Total, Chg in OI, Contracts) — each as a single grouped table with one symbol-header trio per symbol. Deltas are signed (`+37.0` / `-3.2`) and tinted with neutral palette greens/reds. Nulls render as `Not Available`. **Row-count fields are excluded.** |
| `src/ui/news_ticker.py` | **New.** `NewsTicker(QObject)` drives `QTextBrowser.verticalScrollBar()` with a 60 ms `QTimer` (1 px/tick). Hover pauses; mouse-leave resumes; bottom-hold then jump-to-top for a continuous loop. |
| `src/ui/main_window.py` | Observation view now `QTextBrowser` with `setLineWrapMode(NoWrap)`, document margin 0, vertical+horizontal scroll = `ScrollBarAsNeeded`. News view = `QTextBrowser`, document margin 4, both scroll bars `ScrollBarAlwaysOff`, `NewsTicker` wired in. `Load Workspace` button removed. `Lookback` / `News` spin boxes are 52 px wide, range 1–99, centred, with `ButtonSymbols.NoButtons`. Enter on the symbol input *and* on either spin box triggers `_emit_load`. `_emit_load` debounces while a load is in flight. Splitter rebalanced to `[500, 260]` so single-symbol observations fit with zero overflow. |
| `src/workspace_window.py` | `parse_symbols(raw)` splits the input on `,` / `;`, strips whitespace, uppercases, deduplicates preserving order. `run_pipeline(symbols, ...)` accepts a string or iterable and now returns `(observation_html, news_html, news_results: list[NewsResult])`. The controller blocks empty/all-punctuation input with a factual status message. `_format_news_html` accepts a single `NewsResult` (legacy) or a list and emits one anchored news block per symbol with a coloured `═ SYMBOL [timestamp] count: N ═` separator. |
| `src/ui/theme.py` | QSS now collapses `QSpinBox::up-button` / `::down-button` to `0×0` (matches `NoButtons`) and tightens `#LookbackInput` / `#NewsLimitInput` padding to keep the two-digit fields compact. Palette unchanged. |
| `tests/test_ui_workspace.py` | Rewritten: 29 tests covering `parse_symbols`, layout defaults, scrollbar policies, Enter-key triggers (symbol + both spin boxes), HTML observation table content & multi-symbol shape, multi-symbol news rendering, pipeline runs (single, comma-separated, non-existent, timeout), controller guards (blank symbol, only-punctuation symbol), and `NewsTicker` pause/resume on `QEvent.Enter` / `QEvent.Leave`. |
| `tests/_ui_theme_validation_run.py` | Updated to exercise 5 cases: `RELIANCE`, `INFY`, `NIFTY` (single), `RELIANCE, INFY, NIFTY` (multi), `RELIANCE, NONEXISTENT_SYM_123` (mixed). Shows the window and pumps the event loop so reported scrollbar offsets reflect a real viewport. |

---

## 2. Information-Density Changes

### 2.1 Removed fields

| Field | Why |
| --- | --- |
| `Latest F&O Row Count` / `Previous F&O Row Count` | Row counts are a corpus artefact, not a market observation. |
| Separate per-row "Latest …" / "Previous …" pairs in the old text panel | Replaced by `Previous | Latest | Δ` columns in a single row per parameter. |

### 2.2 New table shape (per section)

```
Parameter      Previous     Latest       Δ
Session        2026-05-19   2026-05-20   —
Close          1322.7       1359.7       +37.0
Volume         11000        12345        +1345
Delivery Qty   Not Available  Not Available  Not Available
Delivery %     Not Available  Not Available  Not Available
```

For N symbols, the same `(Previous, Latest, Δ)` trio is repeated N times to the right under a centred symbol header (`colspan=3`). The leftmost `Parameter` column is fixed.

### 2.3 Δ rendering rules

- Numeric deltas are signed with rounded values (`+37.0`, `-3.2`, `0.0`).
- Positive Δ uses `#34D399`; negative `#F87171`; zero / `Not Available` / non-applicable uses `#9CA3AF`. Colour is a deterministic transform of the sign — **no qualitative judgement is inferred**.
- Text fields (`Session`) and one-shot values (`Chg in OI`) render `—` in the unused cells.

### 2.4 Spin boxes

- Width: **52 px** each (was 80 px).
- Range: **1–99** (was 1–365 / 1–50). Lookback never realistically exceeds 99 sessions; news limit never realistically exceeds 99 headlines.
- Step arrows: hidden (`ButtonSymbols.NoButtons`). Values change via keyboard ↑/↓, scroll wheel, or direct typing.
- Text centred, monospaced for terminal feel.

### 2.5 No-button load flow

- The `Load Workspace` button is removed entirely (`findChild(QPushButton, "LoadWorkspaceButton")` returns `None`).
- `QLineEdit.returnPressed` (symbol) and `QSpinBox.lineEdit().returnPressed` (lookback / news) all bind to `_emit_load`.
- `_emit_load` is debounced via `self._symbol_input.isEnabled()` — Qt occasionally double-fires `returnPressed` inside a QSpinBox; the second pulse is silently dropped while a load is in flight.

### 2.6 Multi-symbol news block

```
═ RELIANCE  [25:05:26 11:50:00]  count: 5 ═
Source: The Times of India
Headline: Market recap: 6 of top-10 most-valued firms add Rs 74,111 crore; Reliance biggest winner - The Times of India
URL: https://news.google.com/rss/articles/...   ← clickable
--------------------------------------------------
…
═ INFY  [25:05:26 11:50:00]  count: 5 ═
…
═ NIFTY  [25:05:26 11:50:00]  count: 5 ═
…
```

Each symbol section is rendered in sequence, each with its own anchor URLs, and the whole block scrolls upward as a single ticker.

### 2.7 News ticker rules

- Crawl speed: 1 px / 60 ms (~17 px / s).
- Hover anywhere over the news view → ticker pauses (verified by `eventFilter` capturing `QEvent.Enter` / `QEvent.Leave`).
- Mouse leave → ticker resumes.
- Bottom reached → 25-tick hold (~1.5 s) → jump to top → 12-tick hold → continue.
- `setVerticalScrollBarPolicy(ScrollBarAlwaysOff)` and `setHorizontalScrollBarPolicy(ScrollBarAlwaysOff)` — no scrollbar chrome is ever visible inside the news panel.

---

## 3. Symbols & Cases Tested (live MM parquet + live Google News RSS)

`MM_INSTALL_ROOT = C:\Users\DELL\MMMarket`, lookback = 5, news_limit = 5, news_timeout = 8 s.

| Case | Input | Parsed symbols | UI load | Observation H/V scroll max | News v / h policy | News anchor count | News per-symbol counts | News errors |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| single_RELIANCE | `RELIANCE` | `["RELIANCE"]` | OK | **H = 0, V = 0** | OFF / OFF | 5 | `[5]` | `[None]` |
| single_INFY | `INFY` | `["INFY"]` | OK | **H = 0, V = 0** | OFF / OFF | 5 | `[5]` | `[None]` |
| single_NIFTY | `NIFTY` | `["NIFTY"]` | OK | **H = 0, V = 0** | OFF / OFF | 5 | `[5]` | `[None]` |
| multi_3 | `RELIANCE, INFY, NIFTY` | `["RELIANCE","INFY","NIFTY"]` | OK | **H = 703** (scroll engaged), V = 0 | OFF / OFF | 15 | `[5,5,5]` | `[None,None,None]` |
| multi_with_unknown | `RELIANCE, NONEXISTENT_SYM_123` | `["RELIANCE","NONEXISTENT_SYM_123"]` | OK | H = 136 (scroll engaged), V = 0 | OFF / OFF | 5 | `[5,0]` | `[None,"no_headlines"]` |

Scrollbar verdict:

- **Single-symbol cases show zero scrollbars** (`H = 0`, `V = 0`).
- **Multi-symbol cases gain horizontal scroll on overflow**, exactly as the spec asked.
- The news view never shows a manual scrollbar in any case; the `NewsTicker` `QTimer` is `active=True` for all 5 cases.

---

## 4. Observation Rendering Validation

Sampled cell values scraped from the rendered HTML for each case:

| Case | Symbol(s) | `Close: Latest` | `Close: Δ` | `OI Total: Latest` |
| --- | --- | --- | --- | --- |
| single_RELIANCE | RELIANCE | `1359.7` | `+37.0` | `118900500.0` |
| single_INFY | INFY | `1193.7` | `-3.2` (IEEE-754 artefact rounded) | `67244000.0` |
| single_NIFTY | NIFTY | `Not Available` (cash parquet absent) | `Not Available` | `396523885.0` |
| multi_3 | RELIANCE / INFY / NIFTY | `1359.7` / `1193.7` / `Not Available` | `+37.0` / `-3.2` / `Not Available` | `118900500.0` / `67244000.0` / `396523885.0` |
| multi_with_unknown | RELIANCE / NONEXISTENT_SYM_123 | `1359.7` / `Not Available` | `+37.0` / `Not Available` | `118900500.0` / `Not Available` |

Additional checks for every case:

- `obs_has_cash_header == True`, `obs_has_fo_header == True`.
- `obs_has_row_count_text == False` — the table never references row counts.
- `Not Available` is used wherever an underlying field is null; no `None`, no empty string, no `NaN` leaks through.
- Multi-symbol tables emit one symbol header (`<th class="symbol" colspan="3">`) per symbol per section, plus one `Previous/Latest/Δ` header trio per symbol per section (verified by the test `test_observation_table_multi_symbol_has_per_symbol_columns`: 3 symbols × 2 sections = 6 `>Previous<` / 6 `>Latest<` occurrences).

---

## 5. News Rendering Validation

- Per-symbol counts match upstream RSS: `[5]`, `[5]`, `[5]`, `[5,5,5]`, `[5,0]`.
- Anchor count = sum of per-symbol counts: 5 / 5 / 5 / 15 / 5. (`<a href="…" style="color:#3B82F6">…</a>` per item.)
- `QTextBrowser.openExternalLinks = True` → clicking an anchor still launches the OS default browser; the ticker pauses while the cursor is over the view so anchors are clickable.
- Unicode glyphs (`₹` in INFY headlines, `—` in observation cells) render correctly inside `QTextBrowser`.
- Empty-news symbols (`NONEXISTENT_SYM_123`) render the `Not Available` block with `ERROR: no_headlines`; no anchor is emitted for them.
- `_format_news_html` HTML-escapes `<`, `>`, `&`, `"`, `'` in every field (test `test_news_html_escapes_unsafe_characters` covers a malicious `<script>` headline).

---

## 6. Search & Load Validation

| Behaviour | Result |
| --- | --- |
| Symbol placeholder reads `Enter symbol(s) and press Enter   (e.g. RELIANCE   or   RELIANCE, INFY, NIFTY)` | OK |
| `Load Workspace` button absent (`findChild(QPushButton, "LoadWorkspaceButton") is None`) | OK |
| Enter inside symbol field → `load_requested` emits `(text, lookback, news_limit)` | OK |
| Enter inside `Lookback` / `News` spin box → `load_requested` emits (debounced) | OK |
| Lookback / News range 1–99, default 5, width ≤ 64 px, step arrows hidden | OK |
| Comma-separated input parsed → uppercased, deduplicated, order preserved | OK |
| `;`-separated input parsed identically | OK |
| Blank symbol → controller emits status `error: enter at least one symbol`, no fetch | OK |
| Only-punctuation symbol (`" , , ,"`) → same factual error message, no fetch | OK |
| `Lookback = 0` (range-bypass test) → controller emits `error: lookback must be >= 1` | OK |

---

## 7. Test & Lint Results

```
pytest MM.AI/tests -q                                  →  74 passed, 0 failed
python tests/_ui_theme_validation_run.py               →  exit 0
                                                      (5 cases — single x3, multi-3, multi-with-unknown)
ReadLints (observation_table, news_ticker, main_window,
           workspace_window, theme, test_ui_workspace)  →  no errors
```

New tests added in this step (subset):

- `test_parse_symbols` — 9 parametrised inputs.
- `test_window_defaults_and_size` — placeholder copy, defaults, no `LoadWorkspaceButton`, compact spin width.
- `test_scrollbar_policies` — observation `AsNeeded` both axes, news `AlwaysOff` both axes.
- `test_enter_in_symbol_field_triggers_load` / `test_enter_in_spinboxes_also_triggers_load`.
- `test_observation_table_single_symbol` / `…_multi_symbol_has_per_symbol_columns` / `…_treats_nulls_as_not_available` / `…_empty`.
- `test_news_html_single_result_legacy_signature` / `…_multi_symbol_lists_each_symbol_header`.
- `test_pipeline_multi_symbol_comma_separated`.
- `test_controller_rejects_only_punctuation_symbol`.
- `test_news_ticker_pauses_on_enter_event`.

---

## 8. Warnings / Notes

- The 12 → 24 px vertical overflow observed before the splitter rebalance is now 0 px for every tested case (the splitter is `[500, 260]` and `QTextDocument.setDocumentMargin(0)` on the observation view eliminates Qt's default 4 px gutter).
- `Δ` is rendered as the literal `Δ` character in the table and `&Delta;` in the header (entity to match Qt rich-text rendering). The em-dash `—` for unused cells renders as the actual U+2014 — Windows console output may display `?` instead, but the on-screen render uses the active font's glyph correctly.
- The `obs_h_scroll_max` for the multi-symbol case (703 px and 136 px) is sensitive to the host's font metrics; the *qualitative* behaviour (zero scroll for single symbol, scroll engaged for multi) is invariant.
- Qt occasionally fires `QLineEdit.returnPressed` twice for one Enter inside a `QSpinBox`'s embedded line edit. `_emit_load` short-circuits the duplicate by checking `symbol_input.isEnabled()` (the controller disables inputs the moment the first emission arrives).
- No deprecation warnings, no QSS parse warnings, no Qt plugin warnings during any of the 5 themed validation cases.
