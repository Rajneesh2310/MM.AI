# MM.AI Symbol Search — Validation Report

Scope: when the user types a symbol that does not exactly match anything in
MM's universe, MM.AI now shows likely matches via two complementary UI
surfaces (live autocomplete dropdown + on-submit picker dialog) and lets the
user pick one.

**No MM code modified.** MM.AI reads — strictly read-only — the JSON
catalogue files that MM already maintains.

---

## 1. Files Delivered (inside `MM.AI/` only)

| File | Status | Role |
| --- | --- | --- |
| `src/symbol_catalog.py` | NEW | Read-only adapter over MM's existing `data/cash_symbols.json` + `data/fo_symbols.json`. Falls back to `SYMBOL=*` partition enumeration if those JSON caches are missing. Provides `list_cash_symbols()`, `list_fo_symbols()`, `list_all_symbols()`, `is_known()`, `normalise_query()`, `find_matches()`, `clear_cache()`. |
| `src/ui/symbol_picker.py` | NEW | `SymbolPickerDialog(QDialog)` — modal pick-one-or-cancel dialog showing the top candidates returned by `find_matches`. |
| `src/ui/main_window.py` | EDITED | Added `_LastTokenCompleter` (a `QCompleter` whose `splitPath` / `pathFromIndex` operate on the trailing comma-separated token). Wired it into the symbol input. Added `set_symbol_catalogue(...)` and `completer()` accessors. |
| `src/workspace_window.py` | EDITED | `WorkspaceController` now (a) populates the completer from `list_all_symbols()` on construction and (b) runs `resolve_symbols(...)` before kicking off the pipeline worker. Unknown tokens trigger the picker; cancelled tokens drop. The picker factory is injectable so tests never open a real dialog. |
| `tests/test_symbol_catalog.py` | NEW | 27 unit tests for the catalog adapter (loading, fallback, malformed input, ranking, sanitisation, read-only guarantee, cache behaviour). |
| `tests/test_symbol_picker.py` | NEW | 6 headless dialog tests (candidate listing, accept/reject, OK-disabled when empty, double-click acceptance, blank dedup). |
| `tests/test_symbol_resolution_ui.py` | NEW | 9 UI integration tests (completer wiring, controller resolution flow, picker mocked via `set_picker_factory`). |
| `tests/_symbol_search_validation_run.py` | NEW | Live harness that drives the real catalogue and prints the JSON document used to produce §4 / §5. |
| `symbol-search-report.md` | NEW | This report. |

**Untouched** anywhere under `C:\Users\DELL\Desktop\MM\` and `C:\Users\DELL\MMMarket\`. Verified by inspection — no writes, no file creation, no rename, no deletion of any MM artifact at any code path covered by the tests.

---

## 2. Source of the Symbol Universe

The adapter consumes the catalogue MM already publishes. **No new persistence
is introduced.**

| Priority | Source | Path | Read-only? |
| --- | --- | --- | --- |
| 1 | MM-maintained JSON cache | `<MM_INSTALL_ROOT>/data/cash_symbols.json` | yes — plain `json.loads(read_text(...))` |
| 2 | MM-maintained JSON cache | `<MM_INSTALL_ROOT>/data/fo_symbols.json` | yes |
| 3 | Partition fallback (only if 1+2 missing) | `<MM_INSTALL_ROOT>/data/cash/SYMBOL=*` and `data/fo/SYMBOL=*` | yes — `iterdir()` only |

The MM Python package `mm_backend.symbol_index` is **not** imported by MM.AI. This avoids any risk of triggering `mm_backend/__init__.py` side effects or accidentally hitting MM's write-paths (`rebuild_symbol_cache`, `invalidate_symbol_caches`, `write_web_symbol_catalogs`).

Live counts on this machine at validation time:

```
install_root         : C:\Users\DELL\MMMarket
cash_symbols.json    : exists  (30,245 bytes)
fo_symbols.json      : exists  ( 2,466 bytes)
cash_symbols loaded  : 2,655
fo_symbols loaded    :   222
union (cash ∪ fo)    : 2,660
```

---

## 3. Public API

```python
from src import symbol_catalog

symbol_catalog.list_cash_symbols()                 # tuple[str, ...]  — 2,655 entries
symbol_catalog.list_fo_symbols()                   # tuple[str, ...]  —   222 entries
symbol_catalog.list_all_symbols()                  # tuple[str, ...]  — 2,660 sorted union

symbol_catalog.is_known("RELIANCE")                # True
symbol_catalog.is_known("RELIANC")                 # False
symbol_catalog.normalise_query(" rel-iance@$ ")    # "RELIANCE"

symbol_catalog.find_matches("RELIANC", limit=8)
# -> ['RELIANCE', 'LINC', 'ELIN', 'RELIGARE', 'RELIABLE', 'CREDITACC',
#     'WELINV', 'VELJAN']

symbol_catalog.clear_cache()                       # drop in-memory cache
```

Ranking is deterministic (no scoring randomness, no ML):

1. **Exact match** (the query is itself a symbol).
2. **Prefix** matches, lexically sorted.
3. **Contains** matches, lexically sorted.
4. `difflib.get_close_matches` with cutoff `0.45` for the remainder.

Buckets are filled in order; duplicates are removed; `limit` is honoured strictly.

---

## 4. Live Fuzzy-Match Validation

Run against MM's actual cache files (cash: 2 655, F&O: 222, union: 2 660):

| Query | Exact present? | First 8 suggestions |
| --- | --- | --- |
| `RELIANCE` | yes | RELIANCE, RELIGARE, RELIABLE, VLSFINANCE, RACE, LINC, ELIN, CSLFINANCE |
| `RELIAN` | no | RELIANCE, ELIN, RELIGARE, RELIABLE, WELINV, VELJAN, RHETAN, RELAXO |
| `RELIANC` | no | RELIANCE, LINC, ELIN, RELIGARE, RELIABLE, CREDITACC, WELINV, VELJAN |
| `BANK` | no | BANK10ADD, BANKA, BANKADD, BANKBARODA, BANKBEES, BANKBETA, BANKBETF, BANKETF |
| `INPFY` *(transposition typo)* | no | **INFY**, FINNIFTY, VINNY, NIFTY, INFRA, AXISNIFTY, QNIFTY, NINSYS |
| `NIF` | no | NIF100BEES, NIF100IETF, **NIFTY**, NIFTY1, NIFTY100EW, NIFTYADD, NIFTYBEES, NIFTYBETA |
| `ZZZ_NOTREAL` | no | ZOTA, TREL, MOREALTY, INDHOTEL, ATALREAL, TOTAL, NRAIL, MODTHREAD *(low-quality fuzzy guesses — picker UI lets the user cancel)* |
| `` (blank) | no | *(empty list)* |

Observations:

- For real partial / typo input (`RELIAN`, `RELIANC`, `INPFY`) the **intended** symbol is the top suggestion in every case.
- `BANK` and `NIF` correctly surface the prefix bucket before the contains bucket.
- An empty / whitespace query returns an empty list (no spam suggestions).
- An obviously-bogus query (`ZZZ_NOTREAL`) still returns 8 *closest-by-string* candidates from `difflib`; the picker UI handles this by also allowing the user to **Cancel** and drop the token.

---

## 5. UI End-to-End Validation (headless, `QT_QPA_PLATFORM=offscreen`)

Input typed: `"RELIANCE, RELIANC, ZZZ_NOTREAL"`

| Step | Output |
| --- | --- |
| `parse_symbols(...)` | `['RELIANCE', 'RELIANC', 'ZZZ_NOTREAL']` |
| Completer row count | 2 660 (full union loaded) |
| Picker invocations | 2 (only for the 2 unknown tokens — `RELIANCE` passed through silently) |
| Picker call 1 | query=`RELIANC`, top candidates=`['RELIANCE', 'LINC', 'ELIN', 'RELIGARE', 'RELIABLE', 'CREDITACC', 'WELINV', 'VELJAN']` |
| Picker call 2 | query=`ZZZ_NOTREAL`, top candidates=`['ZOTA', 'TREL', 'MOREALTY', 'INDHOTEL', 'ATALREAL', 'TOTAL', 'NRAIL', 'MODTHREAD']` |
| Resolved (auto-pick first candidate) | `['RELIANCE', 'ZOTA']` |
| Dedup check | `RELIANC` resolved to `RELIANCE` which the user *also* typed — duplicate collapsed in final list |

The `WorkspaceController.resolve_symbols(...)` flow is:

1. `parse_symbols(raw)` → list of normalised tokens.
2. For each token: if `is_known(token)` → pass through.
3. Else → invoke `picker_factory(query, top_candidates, parent)`.
4. If accepted → use the chosen symbol. If cancelled → drop the token.
5. Deduplicate, preserve first-appearance order.
6. If nothing remains → status bar shows `"error: no valid symbols selected (all unknown or cancelled)"`.
7. If the resolved list differs from what the user typed, the symbol input is rewritten to the resolved form so the next Enter press loads exactly what was loaded.

When MM's JSON cache is absent (e.g. an install root that has no MM data), `list_all_symbols()` returns `()` and resolution silently falls back to pass-through — the parquet reader will then report a normal "not available" observation rather than the picker popping for every token.

---

## 6. Two UI Surfaces for "Did You Mean"

| Surface | Trigger | Behaviour |
| --- | --- | --- |
| `QCompleter` popup attached to the symbol input | User starts typing | Live filtered dropdown of matches from the 2,660-symbol catalogue. `MatchContains`, case-insensitive, max 10 visible items. For multi-symbol input the custom `_LastTokenCompleter` only completes the trailing comma-separated token (e.g. `"RELIANCE, IN"` → suggests `INFY`, `INDIGO`, ...). |
| `SymbolPickerDialog` modal | User presses Enter with an unknown token | Top 8 fuzzy matches in a list. `Use Selected` accepts; `Cancel` drops the token. Double-click also accepts. The `Use Selected` button is disabled when the candidate list is empty. |

Both surfaces draw from the same `find_matches(...)` ranking so the user sees a consistent set of suggestions whether they're typing or submitting.

---

## 7. Test & Lint Results

```
pytest MM.AI/tests -q                                  →  181 passed, 0 failed
  (42 new symbol-search tests + 139 previously-passing tests)
python tests/_symbol_search_validation_run.py          →  exit 0
ReadLints (symbol_catalog, symbol_picker, main_window,
           workspace_window, and all new test files)    →  no errors
```

---

## 8. Read-Only / "Don't Change MM" Guarantee

| Concern | Mitigation |
| --- | --- |
| Mutating MM JSON caches | Never written; only `Path.read_text(...)`. Test `test_no_files_are_written_during_lookups` verifies the directory listing is byte-identical before and after every public call. |
| Mutating MM partitions | Never opened for writing; only `Path.iterdir()` over `SYMBOL=*` (fallback path only). |
| Importing `mm_backend` | Not imported. Avoids any risk of `mm_backend/__init__.py` side effects, accidental cache rebuild via `rebuild=True`, or hitting MM's write-paths. |
| Triggering MM's `rebuild_symbol_cache` | Impossible — we don't import the function. |
| Cross-package interference | All new code lives under `MM.AI/src/...`. The only filesystem dependency on MM is the well-known location of the two JSON files inside `<MM_INSTALL_ROOT>/data/`. |

---

## 9. Warnings / Errors

- **None** during live validation.
- `ZZZ_NOTREAL` returns low-quality candidates by design — `difflib` always returns its best 8 guesses if you ask for 8. The picker dialog is the user's escape valve: cancel and the token is dropped.
- When MM is freshly installed and hasn't run a bhav ingest yet (so both JSON caches are absent), `list_all_symbols()` is `()` and the picker is **not** shown for any token — that would be a poor UX in an empty-catalogue state. Resolution silently passes the user's input through to the parquet reader, which then reports a normal "not available" observation. A future refresh by MM will rebuild the JSON caches; `clear_cache()` (or restarting MM.AI) picks them up.
- The in-memory cache lives for the lifetime of the MM.AI process. If MM updates the JSON files mid-session, MM.AI will keep using the snapshot it loaded on first call. This is intentional (avoids re-reading 30 KB on every keystroke); call `symbol_catalog.clear_cache()` to refresh, or restart MM.AI.
