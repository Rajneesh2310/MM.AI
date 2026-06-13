# MM.AI

A separate, read-only conversational market-intelligence layer for the existing MM system.

## What MM.AI is

- **Read-only** consumer of MM's existing Cash and F&O parquet data.
- **Lightweight**, **parquet-driven**, **non-persistent**, **deterministic**.
- **Observable-data-only**: it surfaces what is already on disk in MM, nothing more.

## What MM.AI is NOT

- It does **not** modify any MM file or write under MM's `data/` folder.
- It does **not** store, cache, or persist any state.
- It does **not** predict prices, generate signals, or recommend trades.
- It does **not** introduce a database, cache, queue, message bus, or storage layer.
- It does **not** embed an LLM, UI, or website/news headline fetcher in this scaffold.

## Repository layout (this scaffold)

```
MM.AI/
├── README.md              # This file
├── report.md              # Foundation discovery report (existing MM ecosystem)
├── requirements.txt       # Runtime dependencies (polars) + dev (pytest)
├── src/
│   ├── __init__.py
│   ├── config.py          # MM install/data root resolution
│   ├── models.py          # Plain data containers (SymbolData / CashData / FoData)
│   └── symbol_reader.py   # Read-only symbol reader: load_symbol_data(...)
└── tests/
    ├── __init__.py
    └── test_symbol_reader.py
```

## Resolving MM's data root

MM.AI reads parquet from `<MM_INSTALL_ROOT>/data/cash` and `<MM_INSTALL_ROOT>/data/fo`.
Resolution order (`src/config.py`):

1. `MM_INSTALL_ROOT` environment variable, if set.
2. `mm_install.json` (key `install_root` or `data_root`) beside the running executable — frozen builds only.
3. `~/MMMarket` — developer default.

No path is hard-coded. MM.AI never writes to any of these locations.

## Quick start

```powershell
# 1. install runtime + test dependencies
python -m pip install -r requirements.txt

# 2. point MM.AI at your MM install (one-time)
$env:MM_INSTALL_ROOT = "C:\Users\<you>\MMMarket"   # Windows / PowerShell
# export MM_INSTALL_ROOT="$HOME/MMMarket"           # Linux / macOS

# 3. extract observable rows for a symbol
python -c "from src.symbol_reader import load_symbol_data; print(load_symbol_data('RELIANCE', 5))"
```

## Running the tests

```powershell
pytest tests
```

Tests use temporary parquet shards written into a `tmp_path` directory and a monkey-patched `MM_INSTALL_ROOT`. They never touch a real MM install.

## Scope guardrails

This scaffold provides only:

- MM install-root resolution
- Plain data containers
- A read-only `load_symbol_data(symbol, lookback_sessions)` function

Out of scope (intentionally not implemented here):

- Comparisons between sessions or across symbols
- Rolling averages, rankings, or any derived metrics
- Predictive logic, strategy engines, scoring
- Website headline / news ingestion
- LLM glue and natural-language responses
- UI, web server, or persistent storage

## Discovery report

See [`report.md`](./report.md) for the foundation discovery of the existing MM parquet ecosystem (folder layout, schemas, readers, reusable components, compatibility risks).
