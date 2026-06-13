# MM.AI — Foundation Discovery Report

**Scope:** Read-only inspection of the existing MM codebase (`C:\Users\DELL\Desktop\MM\backend\mm_backend\`) and on-disk parquet at `C:\Users\DELL\MMMarket\data`. No MM files were modified.

**Lineage (documented in MM code):** Session-lineage EOD bhav parquet — **no corporate-action replay, no adjusted price series.**

MM.AI guardrails honored in this report: lightweight, read-only, parquet-driven, non-persistent, non-predictive, deterministic, explainable, observable-data-only. No implementation, no UI, no LLM, no speculative architecture.

---

## 1. Folder Structure Findings

### 1.1 Install-root resolution (`backend/mm_backend/config.py`)

| Mode | Install root source |
|------|---------------------|
| Dev default | `~/MMMarket` |
| Dev override | `MM_INSTALL_ROOT` env var |
| Frozen app | `mm_install.json` beside the exe (`install_root` or `data_root` key) |

All canonical parquet lives under `<install_root>/data/`.

### 1.2 Observed layout (`backend/mm_backend/paths.py`)

```
<install_root>/data/
├── cash/                          # Primary cash EOD parquet store
│   └── SYMBOL=<SYM>/
│       └── YEAR=<YYYY>.parquet
├── fo/                            # Primary F&O EOD parquet store
│   └── SYMBOL=<SYM>/
│       └── YEAR=<YYYY>.parquet
├── cash/raw/delivery/             # Optional MTO sidecar (same partition pattern)
│   └── SYMBOL=<SYM>/YEAR=<YYYY>.parquet
├── manifests/install-manifest.json
├── exports/*.csv                  # Generated CSV exports (not parquet)
├── _rejects/{cash,fo}/*.csv       # Ingest reject artefacts
├── _downloads/nse_bhav/           # CSV staging before ingest
├── logs/{audit,activity}.jsonl
├── corpus_summary.json            # Cached last-session metadata
├── cash_symbols.json / fo_symbols.json
└── _web/{cash,fo}-symbols.json    # UI symbol catalogs
```

### 1.3 Partition contract

- **Pattern:** `data/{cash|fo}/SYMBOL=<SYM>/YEAR=<YYYY>.parquet`
- **Naming:** Hive-style directory keys; one parquet file per (symbol, calendar year)
- **Manifest contract string** (`manifest.py`): `"data/{cash|fo}/SYMBOL=<SYM>/YEAR=<YYYY>.parquet"`
- **Not observed:** Daily consolidated parquet, cross-symbol rollup files, analytics-output parquet files

### 1.4 On-disk corpus observed (`C:\Users\DELL\MMMarket\data`)

| Segment | Symbol dirs | Sample shard |
|---------|-------------|--------------|
| `cash` | 2,655 | `SYMBOL=20MICRONS/YEAR=2026.parquet` |
| `fo` | 222 | `SYMBOL=360ONE/YEAR=2026.parquet` |
| `cash/raw/delivery` | **missing on this install** | — |
| `exports/` | present | `chart_RELIANCE_120.csv`, etc. |
| `manifests/` | present | `install-manifest.json` |

### 1.5 Adjusted vs non-adjusted

- Only **non-adjusted session tape** exists. `bhav_ingest.py` module header states: *“CM + FO bhav only, no corporate-action replay.”*
- Manifest lineage string: `"MM session-lineage EOD bhav parquet; no corporate-action replay"`.

### 1.6 Cash ↔ F&O relationship

- **Separate roots, same partition scheme.** `<install_root>/data/cash` and `<install_root>/data/fo`.
- **Shared join key:** the `SYMBOL` directory name (uppercase NSE ticker).
- **Cash row grain:** one row per `(SYMBOL, DATE)`.
- **F&O row grain:** many rows per session; primary key tuple = `(SYMBOL, DATE, INSTRUMENT, EXPIRY_DT, STRIKE_PR, OPTION_TYP)` (see `FO_DEDUP_KEYS`).

### 1.7 Output / analytics parquet

- None. The only generated parquet are the ingest-written cash/F&O year shards. Generated reports and exports are JSON or CSV (`exports/`, `manifests/`, `corpus_summary.json`, `*_symbols.json`).

---

## 2. Parquet Schema Findings

Schemas below come from **actual Polars reads on disk** (`pl.read_parquet_schema`), cross-checked against `schema.py` and `bhav_ingest.py`.

### 2.1 Cash parquet — observed `SYMBOL=RELIANCE/YEAR=2026.parquet` (92 rows)

| Column | Polars dtype | Notes |
|--------|--------------|-------|
| `SYMBOL` | `String` | Uppercase NSE ticker |
| `DATE` | `Date` | ISO calendar date |
| `OPEN` | `Float64` | |
| `HIGH` | `Float64` | |
| `LOW` | `Float64` | |
| `CLOSE` | `Float64` | |
| `VOLUME` | `Float64` | Total traded quantity |
| `TURNOVER` | `Float64` | |
| `DELIVERY_QTY` | `Float64` | **All 92 sample rows null** |
| `DELIVERY_PERCENT` | `Float64` | **All 92 sample rows null** |
| `YEAR` | `Int32` | Derived at ingest from `DATE.dt.year()` |

- **Observed date range in sample:** 2026-01-01 → 2026-05-20
- **Nullable behavior:** OHLCV populated; delivery columns present but unpopulated in sampled corpus. Across 300 cash symbols sampled for 2026, **300/300 had all-null delivery columns**.
- **Ingest date formats accepted** (`bhav_ingest._date_expr`): `%Y-%m-%d`, then `%d-%b-%Y`, then `%d/%m/%Y` (non-strict, with fallback).
- **Canonical columns** (`schema.CASH_CORE_COLS`):
  ```
  SYMBOL, DATE, OPEN, HIGH, LOW, CLOSE, VOLUME, TURNOVER, DELIVERY_QTY, DELIVERY_PERCENT
  ```
- **Ingest column-map sources** (`CASH_COLUMN_MAP`): UDiFF (`TckrSymb`, `OpnPric`, `TtlTradgVol`, `DelivQty`, …) and legacy NSE (`TIMESTAMP`, `OPEN_PRICE`, `TOTTRDQTY`, `DELIV_QTY`, …).

### 2.2 F&O parquet — observed `SYMBOL=360ONE/YEAR=2026.parquet` (9,780 rows)

| Column | Polars dtype | Notes |
|--------|--------------|-------|
| `INSTRUMENT` | `String` | Sample corpus: only `OPTSTK`, `OPTIDX` observed; `FUTSTK`/`FUTIDX` declared but not seen in 50-file sample |
| `SYMBOL` | `String` | Underlying ticker |
| `DATE` | `Date` | Trade/session date |
| `EXPIRY_DT` | `Date` | Contract expiry |
| `STRIKE_PR` | `Float64` | Strike price |
| `OPTION_TYP` | `String` | `CE`, `PE` (null for futures rows when present) |
| `OPEN` | `Float64` | |
| `HIGH` | `Float64` | |
| `LOW` | `Float64` | |
| `CLOSE` | `Float64` | |
| `SETTLE_PR` | `Float64` | Settlement price |
| `CONTRACTS` | `Float64` | Traded contracts/qty |
| `VAL_INLAKH` | `Float64` | Turnover in lakhs |
| `OPEN_INT` | `Float64` | Open interest (OI) |
| `CHG_IN_OI` | `Float64` | Change in OI |
| `YEAR` | `Int32` | Partition helper |

- **Canonical columns** (`schema.FO_CORE_COLS`): `INSTRUMENT, SYMBOL, DATE, EXPIRY_DT, STRIKE_PR, OPTION_TYP, OPEN, HIGH, LOW, CLOSE, SETTLE_PR, CONTRACTS, VAL_INLAKH, OPEN_INT, CHG_IN_OI`
- **Instrument groups** (`schema.py`): `OPT_INSTRUMENTS = {OPTIDX, OPTSTK}`, `FUT_INSTRUMENTS = {FUTIDX, FUTSTK}`
- **Instrument code normalization** (`bhav_ingest.FO_INSTRUMENT_MAP`): `STF→FUTSTK`, `IDF→FUTIDX`, `STO→OPTSTK`, `IDO→OPTIDX`
- **OI-related fields:** `OPEN_INT`, `CHG_IN_OI`
- **Futures-related fields:** `INSTRUMENT` distinguishes futures via `FUTSTK`/`FUTIDX`; futures rows carry `SETTLE_PR`, `CONTRACTS`, `VAL_INLAKH`, `OPEN_INT`, `CHG_IN_OI` (no `STRIKE_PR`/`OPTION_TYP`)
- **Expiry-related fields:** `EXPIRY_DT` (Date)
- **Derivative metrics present:** `SETTLE_PR`, `CONTRACTS`, `VAL_INLAKH`, `OPEN_INT`, `CHG_IN_OI`
- **Not present:** implied volatility, greeks, lot size, premium turnover separately, futures basis — none in schema.

---

## 3. Reader / Loader Findings

All paths below are under `C:\Users\DELL\Desktop\MM\backend\mm_backend\`.

### 3.1 Primary parquet readers (read-only, symbol-scoped)

| Module | Key functions | Responsibility |
|--------|--------------|----------------|
| `chart_ops.py` | `_read_cash_symbol`, `chart_ohlc_legacy_rows`, `cash_last_snapshot`, `cash_parquet_paths` | Load cash OHLC (+ optional VOLUME/TURNOVER); merge year shards per symbol; apply graphdays cutoff |
| `fo_ops.py` | `_scan_symbol`, `_norm_d`, `fo_trade_dates_for_symbol`, `fo_symbols_for_session`, `fo_expiries`, `fo_option_types`, `fo_option_chain`, `fo_strikes`, `fo_live_pe_chain`, `fo_ce_pe_closes`, `fo_global_trade_dates`, `fo_instruments_global`, `normalize_fo_instrument` | Lazy scan per FO symbol; query expiries, instruments, option chain (CE/PE), strikes (with OI), per-symbol/global session dates |
| `delivery_ops.py` | `_read_cash_parquet_delivery`, `_read_delivery_parquet_dir`, `_read_history_delivery`, `_parse_mto_symbol_frame`, `delivery_by_session` | Multi-source delivery merge (external history → external/local partitions → cash parquet) keyed by ISO session |
| `corpus_meta.py` | `segment_last_session`, `_segment_last_session_cached` | Sample 80 newest parquet files per segment; return max `DATE` |
| `report_ops.py` | `_segment_files`, `_segment_sessions`, `_segment_stats_fast`, `corpus_coverage_report`, `operational_data_report`, `cash_symbol_report`, `market_universe_counts`, `_coverage_from_dates` | Deep or fast corpus statistics; reads only `DATE` column when scanning |
| `manifest.py` | `parquet_row_count`, `_segment_files`, `sha256_file`, `build_install_manifest`, `manifest_dashboard_summary`, `verify_install_manifest` | Schema validation, row counts (`scan_parquet`), SHA256 fingerprints |
| `parquet_scan.py` | `cached_parquet_overview`, `_scan_segment`, `invalidate_parquet_cache` | File count + newest mtime (cap 10,000 files) |

### 3.2 Writers / loaders (NOT for MM.AI consumption — observation only)

| Module | Role |
|--------|------|
| `bhav_ingest.py` | CSV → partitioned parquet; dedup keys `["SYMBOL","DATE"]` (cash) and `FO_DEDUP_KEYS` (fo); persists rejects |
| `external_bhav_bridge.py` | Discover and import external CSV trees → stage → ingest |
| `downloader_range.py` (referenced via `BulkBhavOpts`) | Bulk NSE bhav download |
| `corpus_summary.py` | Writes `corpus_summary.json`; `finalize_overview_after_download`, `rebuild_session_counts_from_corpus` |
| `symbol_index.py` | Writes `cash_symbols.json`, `fo_symbols.json`, `_web/*` |
| `manifest.write_install_manifest`, `verify_install_manifest` | Writes manifest + verifies SHA256 |
| `report_ops.write_csv_export` | Writes CSV under `data/exports/` |
| `audit_log.audit_file_write`, `activity_log` | Append JSONL log files |

### 3.3 Shared utility modules

| Module | Key exports |
|--------|-------------|
| `parquet_utils.py` | `ist_today`, `norm_graph_cutoff`, `to_py_date`, `iso_date`, `parse_float_loose`, `closest_to_average`, `settle_match` |
| `date_fmt.py` | `parse_user_date`, `format_user_date`, `format_user_datetime` |
| `schema.py` | `CASH_CORE_COLS`, `FO_CORE_COLS`, `OPT_INSTRUMENTS`, `FUT_INSTRUMENTS` |
| `paths.py` | `data_root`, `cash_root`, `fo_root`, `delivery_raw_root`, `exports_root`, `rejects_root`, `manifests_root`, `install_manifest_path`, `audit_log_path`, `activity_log_path`, `logs_root`, `bulk_download_jobs_root`, `last_bulk_download_path`, `downloader_manifest_path` |
| `config.py` | `settings.install_root`, `settings.presets_path` |
| `runtime_guard.py` | `assert_under_data_root`, `assert_external_read_only_source`, `assert_not_external_reference_path`, `ensure_runtime_dir`, `configured_external_bhav_roots` — **write guards** (not needed by MM.AI) |

### 3.4 Dispatcher

`query_dispatch.py` provides an in-process `dispatch(action, payload)` / `dispatch_json(...)` facade. Read-only actions reusable by MM.AI:

```
cash_symbols, fo_symbol_universe, symbol_search,
chart_ohlc, fo_dates_global, fo_dates_symbol, fo_instruments,
fo_symbols, fo_expiries, fo_option_types, fo_option_chain,
fo_strikes, fo_live_pe, fo_ce_pe,
dashboard_summary, desk_overview,
cash_report, market_counts,
operational_data_report (deep=false), corpus_coverage_report (deep=false),
formula_bundle, formula_levels_from_preset, presets_list,
external_delivery_discovery, external_bhav_discovery
```

(plus legacy PHP-alias names: `getChartData`, `get_symbol`, `get_exp`, `getStrikePr`, `getOptionType`, `getRateDates`, `live_update`, `getCEPE`).

### 3.5 Dataframe builder pattern (repeated across readers)

```python
# Cash (chart_ops._read_cash_symbol)
sym_dir = cash_root() / f"SYMBOL={symbol.upper()}"
for yf in sorted(sym_dir.glob("YEAR=*.parquet")):
    pl.read_parquet(yf, columns=[...])
pl.concat(frames).with_columns(DATE → _d).filter(_d >= cutoff)

# F&O (fo_ops._scan_symbol)
pl.scan_parquet(sorted(sym_dir.glob("YEAR=*.parquet")))
   .with_columns(pl.col("DATE").cast(Utf8).slice(0,10).str.to_date() → _d)
   .filter(...)
```

---

## 4. Symbol & Date Handling Findings

### 4.1 Symbol lookup

| Mechanism | Location | Behavior |
|-----------|----------|----------|
| Directory scan | `symbol_index._scan_symbol_dirs` | Lists `SYMBOL=*` dirs → uppercase ticker list |
| JSON cache | `data/cash_symbols.json`, `data/fo_symbols.json` | Fast boot; rebuild via `rebuild_symbol_cache` |
| Typeahead search | `symbol_index.search_symbols(segment, query, limit=48)` | Prefix match then contains match; segments `cash`, `fo`, `all` |
| FO index merge | `symbol_index._merge_fo_index_underlyings` | If any of NIFTY / BANKNIFTY / FINNIFTY / MIDCPNIFTY / NIFTYNXT50 present, all five are reported |
| Session FO symbols | `fo_ops.fo_symbols_for_session(rate_date, instrument, max_dirs=800)` | Scans up to 800 symbol dirs and filters by `(DATE, INSTRUMENT)` |
| Cash snapshot lookup | `chart_ops.cash_last_snapshot(symbol)` | Returns last row of merged year shards |
| Missing symbol | Readers return `pl.DataFrame()`, `[]`, or `None` | No exception bubbles to caller |

### 4.2 Date filtering

| Mechanism | Location | Behavior |
|-----------|----------|----------|
| User-supplied date | `date_fmt.parse_user_date` | Accepts `YYYY-MM-DD` or `DD/MM/YYYY` (also `D/M/YYYY`, `D-M-YYYY`, `D.M.YYYY`) |
| Display formatting | `date_fmt.format_user_date`, `format_user_datetime` | `DD/MM/YYYY`, `DD/MM/YYYY HH:MM:SS` |
| Graphdays cutoff | `parquet_utils.norm_graph_cutoff(graphdays)` | `ist_today() - timedelta(days=clamp(1, 365*40))` |
| Internal date normalization | `_norm_date_column` (cash), `_norm_d` (fo) | `pl.col("DATE").cast(Utf8).str.slice(0,10).str.to_date(strict=False)` → alias `_d` |
| Global FO sessions | `fo_ops.fo_global_trade_dates(limit_sessions=150, max_files=500)` | Newest-mtime sample then collect unique `DATE`s |
| Per-symbol FO sessions | `fo_ops.fo_trade_dates_for_symbol(symbol, limit_sessions=120)` | Lazy scan, descending unique dates |
| Per-session FO option types | `fo_ops.fo_option_types(rate_date, instrument, max_symbol_dirs=400)` | Bounded scan |

### 4.3 Latest-date detection

| Source | Method | Caveat |
|--------|--------|--------|
| `corpus_meta.segment_last_session(root, sample=80)` | Max `DATE` across 80 newest files (mtime-sorted) | Heuristic, may miss recently-mtime'd older shards |
| `data/corpus_summary.json` (`corpus_summary.read_corpus_summary`) | `cash_last_session`, `fo_last_session`, `cash_session_dates[-400:]`, `fo_session_dates[-400:]` | Updated on ingest via `note_session`; can lag full corpus |
| `cash_last_snapshot(symbol)` | Symbol's own last row | Symbol-specific |
| `report_ops._segment_sessions` (deep) | Full scan of all `DATE` values | Expensive; explicit `deep=True` only |
| `_last_from_bulk_run(segment)` | Reads `data/_downloads/last_bulk_run.json` | Reflects ingestion not corpus |

### 4.4 Holiday / missing-date / missing-symbol handling

- **Holiday calendar:** Not encoded anywhere in MM. Bulk download uses `skip_weekends=True` (Sat/Sun only).
- **Weekday gap detection** (`report_ops._coverage_from_dates`): walks calendar between min/max session, treats every weekday with no session as a “gap”. NSE holidays therefore appear as gaps.
- **Missing session in F&O query:** functions return `[]` with a `note` key on `fo_live_pe_chain` (`"no_fo_parquet"`, `"bad_date"`, `"no_ce_rows"`, `"no_pe_rows"`).
- **Missing symbol:** returns empty list / empty dataframe / `None`; no raise.
- **Bad user date:** `parse_user_date` raises `ValueError`; callers catch and return empty result.

---

## 5. Existing Analytics Findings

This section documents **only what is implemented today** — no enhancements proposed.

| Category | Exists? | Where / how |
|----------|---------|-------------|
| Cash OHLC time series | Yes | `chart_ops.chart_ohlc_legacy_rows(symbol, graphdays)` |
| Last cash bar | Yes | `chart_ops.cash_last_snapshot(symbol)` |
| Delivery by session (merged sources) | Yes (subject to data availability) | `delivery_ops.delivery_by_session(symbol, graphdays)` |
| F&O option chain (CE + PE per strike, with OI fields) | Yes | `fo_ops.fo_option_chain(rate_date, instrument, symbol, expiry_dt)` |
| F&O strikes (per expiry, with OI, CHG_IN_OI, CONTRACTS) | Yes | `fo_ops.fo_strikes(...)` |
| F&O live PE chain (ref strike = max-OI CE) | Yes | `fo_ops.fo_live_pe_chain`, `_pick_ref_strike` |
| CE/PE close at chosen strikes | Yes | `fo_ops.fo_ce_pe_closes` |
| FO global trade dates / instruments | Yes | `fo_global_trade_dates`, `fo_instruments_global` |
| Fib retracement levels | Yes | `formula_basic.fib_retracement_levels(high, low)` |
| Classic pivot points (R1/R2/R3, S1/S2/S3) | Yes | `formula_basic.classic_pivots(high, low, close)` |
| Gann levels (0,12.5,…,100) | Yes | `formula_basic.gann_levels(high, low)` |
| Combined formula bundle | Yes | `formula_basic.formula_bundle` |
| Preset-driven Fib | Yes | `formula_basic.levels_from_preset` + `preset_ops` |
| Corpus coverage (weekday gaps, first/last session) | Yes | `report_ops.corpus_coverage_report` |
| Symbol-level shard counts and last snapshot | Yes | `report_ops.cash_symbol_report` |
| Market universe counts | Yes | `report_ops.market_universe_counts` |
| Manifest integrity stats / verify | Yes | `manifest.manifest_dashboard_summary`, `verify_install_manifest` |
| CSV export of chart rows | Yes | `report_ops.write_csv_export`, `query_dispatch.export_chart_csv` |
| **Volume comparisons** (rolling avg, ratios) | **No** | — |
| **OI comparisons across sessions** | **No** | Raw OI returned per query only |
| **Delivery comparisons over time** | **No** | Per-session map only |
| **Rolling averages / moving averages** | **No** | — |
| **Rankings / cross-section summaries** | **No** | — |
| **RSI / MACD / Bollinger / other indicators** | **No** | — |
| **Predictive / strategy engines** | **No** | — |
| **Analytics parquet outputs** | **No** | All generated artefacts are CSV/JSON |

### 5.1 Legacy numeric helper

`parquet_utils.closest_to_average(vals)` — picks value nearest arithmetic mean (legacy `live_update.php` settle-pick heuristic). **Not** a time-series rolling average.

### 5.2 Website headline links

- **Not implemented in MM.** The only literal reference is a `news: []` placeholder in `backend/mm_ui/web/desk.js`. No news/RSS fetchers, no headline parsers, no NSE-link extractors.

---

## 6. Reusable Components (Safe vs Tightly Coupled)

### 6.1 Safe for MM.AI read-only consumption

| Component | Why safe |
|-----------|----------|
| `schema.py` | Pure column-name and instrument-set contracts; no I/O |
| `paths.py` + `config.settings.install_root` | Pure path resolution |
| `parquet_utils.py` | Date/numeric coercion; pure functions |
| `date_fmt.py` | Parse/format only |
| `chart_ops._read_cash_symbol`, `chart_ohlc_legacy_rows`, `cash_last_snapshot`, `cash_parquet_paths` | Read parquet, deterministic |
| `fo_ops` query functions (all the `fo_*` getters listed in §3.1) | Read-only lazy scans |
| `delivery_ops.delivery_by_session` | Read-only merge (caveat: relies on data being populated) |
| `symbol_index.list_cash_symbols_cached(rebuild=False)`, `list_fo_symbols_cached(rebuild=False)`, `search_symbols` | Read JSON cache or scan dirs |
| `corpus_meta.segment_last_session` | Bounded read |
| `manifest.parquet_row_count`, `_segment_files` (read-only) | Schema-validation patterns |
| `formula_basic.*` | Pure math on user-supplied H/L/C |
| `query_dispatch.dispatch` (read-only actions only — listed in §3.4) | In-process facade |

### 6.2 Tightly coupled — MM.AI should NOT depend on these

| Component | Reason |
|-----------|--------|
| `bhav_ingest.*` | Writes parquet under `data/{cash,fo}` |
| `external_bhav_bridge.*` | Imports/copies CSVs and ingests |
| `downloader_range.run_bulk_bhav_download` | Network downloads + writes |
| `corpus_summary.write_corpus_summary`, `note_session`, `finalize_overview_after_download`, `rebuild_session_counts_from_corpus` | Persists JSON |
| `symbol_index.rebuild_symbol_cache`, `write_web_symbol_catalogs`, `invalidate_symbol_caches` | Writes cache files |
| `manifest.write_install_manifest`, `verify_install_manifest` | Heavy I/O + writes |
| `report_ops.write_csv_export`, deep `_segment_sessions`, `rebuild_session_counts_from_corpus` | Writes CSV / full corpus scan |
| `runtime_guard.assert_under_data_root`, `ensure_runtime_dir` | Write guards (irrelevant for read-only) |
| `audit_log.audit_file_write`, `activity_log` | Append JSONL logs |
| Full `query_dispatch.ACTIONS` table (mixed read/write) | Contains write actions (`write_install_manifest`, `bulk_bhav_download`, `import_external_bhav_to_mm`, `run_external_bhav_import_range`, `refresh_data_overview`, `export_*_csv`, `run_golden_suite`) |

---

## 7. MM.AI Compatibility Risks (Observation Only)

| Risk | Observed evidence |
|------|-------------------|
| **Unpopulated delivery columns** | 300/300 sampled cash 2026 shards: all `DELIVERY_QTY` / `DELIVERY_PERCENT` null; `data/cash/raw/delivery` absent on dev install |
| **Fragmented delivery sources** | `delivery_by_session` merges four-tier sources (external history → external partitions → MM partitions → cash parquet) with later-source override — outcome depends on environment env vars |
| **No adjusted prices** | Splits/bonuses not replayed; long-horizon series can be discontinuous |
| **Year-sharded reads** | Multi-year queries require glob + `pl.concat`/`pl.scan_parquet` per symbol |
| **Bounded F&O scans** | `fo_symbols_for_session` (max 800 dirs), `fo_option_types` (400 dirs), `fo_global_trade_dates` (500 files), `fo_instruments_global` (180 dirs × 2 years) — incomplete on very large installs |
| **Latest-session heuristics** | `segment_last_session` samples 80 mtime-sorted files; `corpus_summary` tracks ingest not corpus max; can disagree with true latest `DATE` |
| **Weekday-only gap logic** | NSE trading holidays show as “gaps” in `corpus_coverage_report` |
| **Instrument coverage in sample** | Sampled F&O corpus is options-only (`OPTSTK`/`OPTIDX`); `FUTSTK`/`FUTIDX` exist in schema but absent from 50-file sample — coverage is corpus-dependent |
| **Stale symbol caches** | `cash_symbols.json` / `fo_symbols.json` lag disk until rebuild; cached path only read when not rebuilt |
| **FO index injection side-effect** | Any one NSE index underlying triggers all five being reported by `list_fo_symbols_cached` |
| **Hardcoded path divergence in dev** | Dev data at `~/MMMarket/data` vs frozen install under `mm_install.json` — MM.AI must resolve `install_root` explicitly |
| **Date-parser fallback chain** | `_date_expr` tries three formats non-strict — silent miss yields null `DATE` and rejects |
| **No headline infrastructure** | No existing module to reuse for MM.AI’s “live website headline links only” requirement |
| **In-process coupling cost** | Importing `mm_backend` pulls Polars, pydantic-settings, runtime-guard write logic — not zero-dependency |
| **Read-on-write contention** | Concurrent read while ingest writes a year shard is unguarded by any lock |
| **CSV legacy formats** | Multiple historical NSE column conventions mapped (UDiFF + legacy + ZIP variants) — MM.AI is downstream of parquet so unaffected, but schema drift across years possible |

---

## 8. Recommended Read-Only Integration Points

For a separate lightweight MM.AI layer — **observation, not implementation:**

1. **Resolve data root once** — `from mm_backend.config import settings` then `settings.install_root`, or import `mm_backend.paths.cash_root()` / `fo_root()`.
2. **Read cash series** — mirror `chart_ops._read_cash_symbol(symbol, cutoff)`: column-projected year shards, `_d` normalization, IST cutoff via `parquet_utils.norm_graph_cutoff`.
3. **Read F&O for symbol/session** — mirror `fo_ops._scan_symbol` + `_norm_d` then filter on `_d`, `INSTRUMENT`, `EXPIRY_DT`, `OPTION_TYP`.
4. **Symbol discovery** — `symbol_index.list_cash_symbols_cached(rebuild=False)`, `list_fo_symbols_cached(rebuild=False)`, `search_symbols`; or direct `SYMBOL=*` glob if cache-free behavior is preferred.
5. **User-date parsing** — `date_fmt.parse_user_date`; display via `format_user_date`.
6. **Latest session hint** — `corpus_summary.read_corpus_summary()` keys (`cash_last_session`, `fo_last_session`) or bounded `corpus_meta.segment_last_session(cash_root())`. Document the heuristic to end users.
7. **Delivery** — call `delivery_ops.delivery_by_session`; treat null-heavy or empty result as expected on installs where delivery data is not present.
8. **Deterministic derived levels** — `formula_basic.formula_bundle(high, low, close)` if MM.AI surfaces pivots / Fib / Gann from user-supplied OHLC; no learned models.
9. **Headlines / website links** — **no MM module exists**; MM.AI must source these externally (in-memory only per the non-persistent guardrail).
10. **Avoid in MM.AI default path** — any function in §6.2 (ingest, manifest write, corpus rebuild, CSV export, bulk download, deep corpus scans, audit/activity logs, write guards).

---

## Summary

MM’s parquet ecosystem is a **dual-store, symbol-partitioned, year-sharded, session-lineage EOD corpus** under `<install_root>/data/{cash,fo}`. Schemas are stable and documented in `schema.py`; on-disk files add the `YEAR` column. Readers are concentrated in `chart_ops`, `fo_ops`, and `delivery_ops`, with shared date/symbol utilities in `parquet_utils`, `date_fmt`, `symbol_index`, and `paths`. Existing analytics are **query-time extractions** (OHLC, option chains, OI fields, formula levels, coverage reports) — not rolling metrics, rankings, or ML. The primary data-quality gap for MM.AI is **unpopulated delivery columns in the observed cash corpus** and **absence of any headline/link subsystem** in MM.

No MM code was changed during this discovery.
