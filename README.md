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

## Repository layout

```text
MM.AI/
|-- README.md              # This file
|-- report.md              # Foundation discovery report (existing MM ecosystem)
|-- requirements.txt       # Runtime dependencies (polars) + dev (pytest)
|-- src/
|   |-- __init__.py
|   |-- config.py          # MM install/data root resolution
|   |-- models.py          # Plain data containers (SymbolData / CashData / FoData)
|   `-- symbol_reader.py   # Read-only symbol reader: load_symbol_data(...)
`-- tests/
    |-- __init__.py
    `-- test_symbol_reader.py
```

## Resolving MM's data root

MM.AI reads parquet from a single data folder containing `cash/` and `fo/`.
Resolution order (`src/config.py`):

1. `MM_DATA_ROOT` environment variable, if set. This is the direct data folder, e.g. `/opt/mm-web-data`.
2. `MM_INSTALL_ROOT` environment variable, if set. MM.AI reads `<MM_INSTALL_ROOT>/data`.
3. `mm_install.json` (key `install_root` or `data_root`) beside the running executable - frozen builds only.
4. `/opt/mm-web-data` on Linux/VPS.
5. `~/MMMarket/data` on Windows/dev.

No path is hard-coded. MM.AI never writes to any of these locations.

For VPS deployments running MMWeb, no data-root env var is required if the data
folder is at the standard path:

```bash
/opt/mm-web-data
```

You can still override it if needed:

```bash
export MM_DATA_ROOT=/opt/mm-web-data
```

Do not set `MM_INSTALL_ROOT=/opt/mm-web-data` on VPS. `MM_INSTALL_ROOT` is an
install folder, so MM.AI would look under `/opt/mm-web-data/data`, which is not
the MMWeb data folder.

## Quick start

```powershell
# 1. install runtime + test dependencies
python -m pip install -r requirements.txt

# 2. point MM.AI at your MM install/data root (one-time)
$env:MM_DATA_ROOT = "C:\Users\<you>\MMMarket\data" # Windows / PowerShell
$env:MM_INSTALL_ROOT = "C:\Users\<you>\MMMarket"   # Windows / PowerShell
# export MM_DATA_ROOT="$HOME/MMMarket/data"         # Linux / macOS
# export MM_INSTALL_ROOT="$HOME/MMMarket"           # Linux / macOS

# 3. extract observable rows for a symbol
python -c "from src.symbol_reader import load_symbol_data; print(load_symbol_data('RELIANCE', 5))"
```

## Web UI on VPS

MM.AI includes a small browser UI/API for headless VPS use. It runs separately
from MMWeb and reads the same default VPS data folder, `/opt/mm-web-data`.

```bash
cd /opt/mm-ai
. .venv/bin/activate
python -m src.web_app --host 0.0.0.0 --port 3010
```

With PM2:

```bash
cd /opt/mm-ai
MM_AI_WEB_PORT=3010 pm2 start .venv/bin/python --name mm-ai -- -m src.web_app --host 0.0.0.0 --port 3010
pm2 save
```

Open:

```text
http://<vps-ip>:3010
```

## Running the tests

```powershell
pytest tests
```

Tests use temporary parquet shards written into a `tmp_path` directory and monkey-patched data-root environment variables. They never touch a real MM install.

## Scope guardrails

This scaffold provides only:

- MM install/data-root resolution
- Plain data containers
- A read-only `load_symbol_data(symbol, lookback_sessions)` function

Out of scope (intentionally not implemented here):

- Comparisons between sessions or across symbols
- Rolling averages, rankings, or any derived metrics
- Predictions, signals, recommendations, sentiment, or explanations
- UI, web server, or persistent storage

See `report.md` for the foundation discovery of the existing MM parquet ecosystem.
