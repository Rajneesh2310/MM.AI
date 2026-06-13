"""Small browser UI/API for MM.AI on headless VPS deployments.

This module intentionally uses Python's standard-library HTTP server. It keeps
deployment simple: the existing MM.AI pipeline, local Ollama adapter, and
``/opt/mm-web-data`` default are reused without introducing another framework.
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass, field, replace
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from html import escape
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from . import config, symbol_catalog
from .llm_adapter import generate_llm_response, probe_endpoint
from .llm_config import load_config_from_env
from .llm_prompt_builder import build_llm_prompt
from .news_fetcher import DEFAULT_TIMEOUT_SECONDS
from .models import SymbolData
from .news_models import NewsResult
from .observation_builder import build_observations
from .symbol_reader import load_symbol_data
from .text_formatter import format_observations
from .news_fetcher import fetch_symbol_news

DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 3010
MAX_BODY_BYTES = 64_000

_SYMBOL_ALIASES: dict[str, str] = {
    "HDFC": "HDFCBANK",
    "HDFC BANK": "HDFCBANK",
    "STATE BANK OF INDIA": "SBIN",
    "SBI": "SBIN",
    "AUROBINDO": "AUROPHARMA",
    "AUROBINDO PHARMA": "AUROPHARMA",
    "JSW": "JSWSTEEL",
    "JSW STEEL": "JSWSTEEL",
}

_NEWS_QUERIES: dict[str, str] = {
    "HDFCBANK": "HDFC Bank",
    "SBIN": "State Bank of India SBI",
    "AUROPHARMA": "Aurobindo Pharma",
    "JSWSTEEL": "JSW Steel",
    "BANKNIFTY": "Bank Nifty",
    "NIFTY": "Nifty 50",
}


@dataclass
class WebState:
    symbols: list[str] = field(default_factory=list)
    observation_html: str = ""
    news_html: str = ""
    data_inventory_html: str = ""
    data_inventory_text: str = ""
    workspace_text: str = ""
    prompt_text: str = ""
    news_results: list[Any] = field(default_factory=list)
    status: str = "ready"


STATE = WebState()


def _resolve_symbol(raw_symbol: str) -> str:
    sym = raw_symbol.strip().upper()
    alias_key = " ".join(sym.replace(".", " ").split())
    if alias_key in _SYMBOL_ALIASES:
        return _SYMBOL_ALIASES[alias_key]
    cleaned = symbol_catalog.normalise_query(sym)
    if cleaned and symbol_catalog.is_known(cleaned):
        return cleaned
    matches = symbol_catalog.find_matches(cleaned, limit=1)
    return matches[0] if matches else cleaned


def parse_symbols(raw: str | None) -> list[str]:
    if not raw:
        return []
    seen: dict[str, None] = {}
    for part in raw.replace(";", ",").split(","):
        sym = _resolve_symbol(part)
        if sym and sym not in seen:
            seen[sym] = None
    return list(seen.keys())


def _empty_observation(symbol: str, lookback: int) -> dict[str, Any]:
    return {"symbol": symbol, "lookback_sessions": lookback, "cash": {}, "fo": {}}


def _build_observations_for_symbol(symbol: str, lookback: int) -> dict[str, Any]:
    try:
        return build_observations(load_symbol_data(symbol, lookback_sessions=lookback))
    except Exception:  # noqa: BLE001
        return _empty_observation(symbol, lookback)


def _workspace_text_for_symbols(symbols: list[str], lookback: int) -> str:
    blocks: list[str] = []
    for sym in symbols:
        try:
            symbol_data = load_symbol_data(sym, lookback_sessions=lookback)
            obs = build_observations(symbol_data)
            blocks.append(format_observations(obs))
            extra = _extra_market_context(symbol_data)
            if extra:
                blocks.append(extra)
        except Exception as exc:  # noqa: BLE001
            blocks.append(f"SYMBOL: {sym}\n(observation unavailable: {type(exc).__name__})\n")
    return "\n\n".join(blocks)


def _sorted_unique_text(values: list[Any]) -> list[str]:
    seen: dict[str, None] = {}
    for value in values:
        text = str(value).strip()
        if text and text not in seen:
            seen[text] = None
    return sorted(seen)


def _expiry_values(rows: list[dict[str, Any]]) -> list[str]:
    expiry_cols = (
        "EXPIRY_DT",
        "EXPIRY_DATE",
        "EXPIRY",
        "EXPIRYDATE",
        "CONTRACT_EXPIRY",
    )
    values: list[Any] = []
    for row in rows:
        for col in expiry_cols:
            if col in row and row.get(col) not in (None, ""):
                values.append(row.get(col))
                break
    return _sorted_unique_text(values)


def _row_columns(rows: list[dict[str, Any]]) -> list[str]:
    cols: dict[str, None] = {}
    for row in rows[:10]:
        for key in row:
            cols[str(key)] = None
    return sorted(cols)


def _extra_market_context(symbol_data: SymbolData) -> str:
    cash_rows = [symbol_data.cash.latest_row] if symbol_data.cash.latest_row else []
    fo_rows = list(symbol_data.fo.latest_session_rows)
    lines: list[str] = [
        f"SYMBOL: {symbol_data.symbol}",
        "RAW DATA AVAILABILITY",
        f"Cash columns: {', '.join(_row_columns(cash_rows)) or 'Not Available'}",
        f"F&O columns: {', '.join(_row_columns(fo_rows)) or 'Not Available'}",
        f"Latest F&O expiry dates: {', '.join(_expiry_values(fo_rows)) or 'Not Available'}",
    ]
    return "\n".join(lines) + "\n"


def _observation_html(observations: list[dict[str, Any]]) -> str:
    text = "\n\n".join(format_observations(obs) for obs in observations)
    return f"<pre>{escape(text)}</pre>"


def _news_html(results: list[NewsResult]) -> str:
    parts: list[str] = []
    for result in results:
        parts.append(f"<h3>{escape(result.symbol)}</h3>")
        if result.error:
            parts.append(f"<p>ERROR: {escape(result.error)}</p>")
        if not result.items:
            parts.append("<p>Not Available</p>")
            continue
        parts.append("<ul>")
        for item in result.items:
            headline = escape(item.headline or "Not Available")
            source = escape(item.source or "")
            url = escape(item.url or "", quote=True)
            published_at = escape(getattr(item, "published_at", "") or "publish date unavailable")
            if url:
                parts.append(f'<li><time>{published_at}</time> <a href="{url}" target="_blank" rel="noreferrer">{headline}</a> <small>{source}</small></li>')
            else:
                parts.append(f"<li><time>{published_at}</time> {headline} <small>{source}</small></li>")
        parts.append("</ul>")
    return "".join(parts) if parts else "<p>No news loaded.</p>"


def _news_query_for_symbol(symbol: str) -> str:
    return _NEWS_QUERIES.get(symbol.strip().upper(), symbol)


def _fetch_news_for_symbol(symbol: str, *, limit: int, timeout: float) -> NewsResult:
    result = fetch_symbol_news(_news_query_for_symbol(symbol), limit=limit, timeout=timeout)
    return replace(result, symbol=symbol)


def _parquet_files(root: Path, symbol: str) -> list[Path]:
    sym_dir = root / f"SYMBOL={symbol}"
    if not sym_dir.is_dir():
        return []
    try:
        return sorted(sym_dir.glob("YEAR=*.parquet"))
    except OSError:
        return []


def _data_inventory(symbols: list[str]) -> tuple[str, str]:
    lines: list[str] = [
        f"DATA ROOT: {config.data_root()}",
        f"CASH ROOT: {config.cash_root()}",
        f"F&O ROOT: {config.fo_root()}",
        "",
    ]
    html_parts: list[str] = [
        f"<p><strong>Data root:</strong> {escape(str(config.data_root()))}</p>",
        "<table><thead><tr><th>Symbol</th><th>Segment</th><th>Parquet files available</th></tr></thead><tbody>",
    ]
    for sym in symbols:
        for segment, root in (("cash", config.cash_root()), ("fo", config.fo_root())):
            files = _parquet_files(root, sym)
            lines.append(f"{sym} / {segment}:")
            if files:
                file_lines = []
                for fp in files:
                    try:
                        stat = fp.stat()
                        detail = f"{fp.name} ({stat.st_size:,} bytes)"
                    except OSError:
                        detail = fp.name
                    lines.append(f"  - {fp}")
                    file_lines.append(escape(detail))
                html_files = "<br>".join(file_lines)
            else:
                lines.append("  - Not Available")
                html_files = "<em>Not Available</em>"
            html_parts.append(
                f"<tr><td>{escape(sym)}</td><td>{escape(segment)}</td><td>{html_files}</td></tr>"
            )
        lines.append("")
    html_parts.append("</tbody></table>")
    return "".join(html_parts), "\n".join(lines).rstrip()


def run_pipeline(
    symbols: list[str],
    *,
    lookback: int,
    news_limit: int,
    news_timeout: float,
) -> tuple[str, str, list[NewsResult]]:
    observations = [_build_observations_for_symbol(sym, lookback) for sym in symbols]
    news_results = [
        _fetch_news_for_symbol(sym, limit=news_limit, timeout=news_timeout)
        for sym in symbols
    ]
    return _observation_html(observations), _news_html(news_results), news_results


def _jsonable_news(result: Any) -> dict[str, Any]:
    return {
        "symbol": getattr(result, "symbol", ""),
        "timestamp": getattr(result, "timestamp", ""),
        "count": getattr(result, "count", 0),
        "error": getattr(result, "error", None),
        "items": [
            {
                "source": getattr(item, "source", ""),
                "headline": getattr(item, "headline", ""),
                "url": getattr(item, "url", ""),
                "timestamp": getattr(item, "timestamp", ""),
                "published_at": getattr(item, "published_at", ""),
            }
            for item in getattr(result, "items", [])
        ],
    }


def health_payload() -> dict[str, Any]:
    llm_cfg = load_config_from_env()
    return {
        "ok": True,
        "data_root": str(config.data_root()),
        "cash_root": str(config.cash_root()),
        "fo_root": str(config.fo_root()),
        "llm": {
            "config": llm_cfg.as_dict(),
            "probe": probe_endpoint(llm_cfg),
        },
    }


def load_workspace(payload: dict[str, Any], state: WebState = STATE) -> dict[str, Any]:
    raw_symbols = str(payload.get("symbols") or payload.get("symbol") or "")
    symbols = parse_symbols(raw_symbols)
    if not symbols:
        return {"ok": False, "error": "enter at least one symbol"}
    lookback = int(payload.get("lookback") or 5)
    news_limit = int(payload.get("news_limit") or 5)
    if lookback < 1:
        return {"ok": False, "error": "lookback must be >= 1"}
    if news_limit < 1:
        return {"ok": False, "error": "news_limit must be >= 1"}

    obs_html, news_html, news_results = run_pipeline(
        symbols,
        lookback=lookback,
        news_limit=news_limit,
        news_timeout=DEFAULT_TIMEOUT_SECONDS,
    )
    workspace_text = _workspace_text_for_symbols(symbols, lookback)
    data_inventory_html, data_inventory_text = _data_inventory(symbols)
    status = f"loaded {len(symbols)} symbol(s) - news: {sum(r.count for r in news_results)}"

    state.symbols = symbols
    state.observation_html = obs_html
    state.news_html = news_html
    state.data_inventory_html = data_inventory_html
    state.data_inventory_text = data_inventory_text
    state.workspace_text = workspace_text
    state.prompt_text = ""
    state.news_results = list(news_results)
    state.status = status

    return {
        "ok": True,
        "symbols": symbols,
        "status": status,
        "observation_html": obs_html,
        "news_html": news_html,
        "data_inventory_html": data_inventory_html,
        "data_inventory_text": data_inventory_text,
        "workspace_text": workspace_text,
        "news_results": [_jsonable_news(r) for r in news_results],
    }


def ask_question(payload: dict[str, Any], state: WebState = STATE) -> dict[str, Any]:
    question = str(payload.get("question") or "").strip()
    if not question:
        return {"ok": False, "kind": "error", "error": "Enter a market question."}

    if payload.get("symbols") or payload.get("symbol"):
        load_result = load_workspace(payload, state)
        if not load_result.get("ok"):
            return load_result

    try:
        payload_obj = build_llm_prompt(
            user_question=question,
            workspace_html=state.observation_html,
            workspace_text=state.workspace_text,
            news_items=state.news_results,
            symbols=state.symbols,
        )
        state.prompt_text = payload_obj.prompt_text
        response = generate_llm_response(payload_obj, load_config_from_env())
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "kind": "error",
            "timestamp": "",
            "response_text": f"{type(exc).__name__}: {exc}",
            "symbols": state.symbols,
            "prompt_text": state.prompt_text,
        }
    kind = "ok" if response.ok else "error"
    text = response.response_text if response.ok else (response.error or "Market response unavailable.")
    return {
        "ok": response.ok,
        "kind": kind,
        "timestamp": response.timestamp,
        "response_text": text,
        "symbols": state.symbols,
        "prompt_text": state.prompt_text,
    }


INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>MM.AI</title>
  <style>
    :root { color-scheme: dark; --bg:#07090d; --panel:#10151d; --line:#263241; --text:#e8edf4; --muted:#98a7b7; --accent:#36d399; --warn:#f6c453; --bad:#ff6b6b; }
    * { box-sizing: border-box; }
    body { margin:0; background:var(--bg); color:var(--text); font:14px/1.45 system-ui,Segoe UI,Arial,sans-serif; }
    header { display:flex; align-items:center; justify-content:space-between; padding:14px 18px; border-bottom:1px solid var(--line); background:#0b1017; }
    h1 { margin:0; font-size:18px; letter-spacing:0; }
    main { display:grid; grid-template-columns:minmax(300px, 360px) minmax(420px, 1fr) minmax(420px, 1fr); gap:14px; padding:14px; min-height:calc(100vh - 55px); }
    section, aside { background:var(--panel); border:1px solid var(--line); border-radius:8px; }
    aside { padding:14px; display:flex; flex-direction:column; gap:12px; }
    section { overflow:hidden; }
    .section-head { display:flex; align-items:center; justify-content:space-between; gap:10px; padding:10px 14px; border-bottom:1px solid var(--line); background:#0d131b; }
    .section-head h2 { margin:0; font-size:14px; }
    label { color:var(--muted); font-size:12px; display:block; margin-bottom:5px; }
    input, textarea, button { width:100%; border:1px solid var(--line); border-radius:6px; background:#080d13; color:var(--text); padding:10px; font:inherit; }
    textarea { min-height:105px; resize:vertical; }
    button { background:#123221; border-color:#1d6f45; cursor:pointer; font-weight:650; }
    button:disabled { opacity:.55; cursor:wait; }
    .row { display:grid; grid-template-columns:1fr 1fr; gap:10px; }
    .status { color:var(--muted); min-height:20px; }
    .panel-body { padding:14px; overflow:auto; height:calc(100vh - 118px); }
    .split { display:grid; gap:14px; }
    .block { border:1px solid var(--line); border-radius:6px; overflow:hidden; background:#080d13; }
    .block h3 { margin:0; padding:8px 10px; border-bottom:1px solid var(--line); background:#0b1017; font-size:13px; }
    .block-content { padding:10px; max-height:36vh; overflow:auto; }
    pre { white-space:pre-wrap; word-break:break-word; margin:0; color:var(--text); }
    table { width:100%; border-collapse:collapse; font-size:12px; }
    th, td { border-bottom:1px solid var(--line); padding:7px; text-align:left; vertical-align:top; }
    th { color:var(--muted); background:#0b1017; position:sticky; top:0; }
    time { display:inline-block; min-width:155px; color:var(--warn); font-size:12px; }
    li { margin:7px 0; }
    iframe { width:100%; height:100%; border:0; background:white; border-radius:6px; }
    .answer { padding:12px; border:1px solid var(--line); border-radius:6px; background:#080d13; white-space:pre-wrap; min-height:120px; }
    .prompt { padding:12px; border:1px solid var(--line); border-radius:6px; background:#080d13; white-space:pre-wrap; min-height:260px; overflow:auto; font-family:ui-monospace,Consolas,monospace; font-size:12px; }
    .health { font-family:ui-monospace,Consolas,monospace; font-size:12px; color:var(--muted); white-space:pre-wrap; }
    @media (max-width: 1200px) { main { grid-template-columns:1fr; } .panel-body { height:auto; max-height:70vh; } }
  </style>
</head>
<body>
  <header><h1>MM.AI</h1><div id="topStatus" class="status">checking...</div></header>
  <main>
    <aside>
      <div><label>Symbols</label><input id="symbols" value="RELIANCE" placeholder="RELIANCE, INFY, NIFTY"></div>
      <div class="row">
        <div><label>Lookback</label><input id="lookback" type="number" min="1" value="5"></div>
        <div><label>News limit</label><input id="newsLimit" type="number" min="1" value="5"></div>
      </div>
      <button id="loadBtn">Load Workspace</button>
      <div><label>Question</label><textarea id="question" placeholder="What changed in RELIANCE today?"></textarea></div>
      <button id="askBtn">Ask MM.AI</button>
      <div id="status" class="status"></div>
      <div id="health" class="health"></div>
    </aside>
    <section>
      <div class="section-head"><h2>Data Available To Script</h2><span id="symbolStatus" class="status"></span></div>
      <div class="panel-body split">
        <div class="block"><h3>Parquet Files</h3><div id="inventory" class="block-content"><pre>No data loaded.</pre></div></div>
        <div class="block"><h3>Observable Market Data</h3><div id="obs" class="block-content"><pre>No workspace loaded.</pre></div></div>
      </div>
    </section>
    <section>
      <div class="section-head"><h2>LLM Prompt And Output</h2><span id="llmStatus" class="status"></span></div>
      <div class="panel-body split">
        <div class="block"><h3>News Ticker - Latest Published First</h3><div id="news" class="block-content"><pre>No news loaded.</pre></div></div>
        <div class="block"><h3>Prompt Sent To LLM</h3><pre id="prompt" class="prompt">No prompt sent yet.</pre></div>
        <div class="block"><h3>LLM Output</h3><div id="answer" class="answer"></div></div>
      </div>
    </section>
  </main>
  <script>
    const $ = (id) => document.getElementById(id);
    const state = { workspaceText: "" };
    let lastLoad = null;
    function payload() {
      return { symbols: $("symbols").value, lookback: Number($("lookback").value || 5), news_limit: Number($("newsLimit").value || 5) };
    }
    async function post(path, body) {
      const res = await fetch(path, { method:"POST", headers:{ "Content-Type":"application/json" }, body:JSON.stringify(body) });
      return await res.json();
    }
    function busy(on) { $("loadBtn").disabled = on; $("askBtn").disabled = on; }
    function showWorkspace(data) {
      $("inventory").innerHTML = data.data_inventory_html || "<pre>No data inventory.</pre>";
      $("obs").innerHTML = data.observation_html || "<pre>No observations.</pre>";
      $("news").innerHTML = data.news_html || "<pre>No news.</pre>";
      state.workspaceText = data.workspace_text || "";
      $("symbolStatus").textContent = (data.symbols || []).join(", ");
    }
    async function loadWorkspace({ silent = false } = {}) {
      busy(true); if (!silent) $("status").textContent = "Loading workspace...";
      try {
        const body = payload();
        const data = await post("/api/load", body);
        if (!data.ok) throw new Error(data.error || "load failed");
        lastLoad = body;
        showWorkspace(data); $("status").textContent = `${data.status} | refreshed ${new Date().toLocaleTimeString()}`;
      } catch (e) { $("status").textContent = e.message; }
      finally { busy(false); }
    }
    $("loadBtn").onclick = () => loadWorkspace();
    $("askBtn").onclick = async () => {
      busy(true); $("status").textContent = "Generating...";
      try {
        const data = await post("/api/ask", { ...payload(), question: $("question").value });
        $("answer").textContent = data.response_text || data.error || "";
        $("prompt").textContent = data.prompt_text || "No prompt returned.";
        $("status").textContent = `${data.kind || "response"} ${data.timestamp || ""}`;
        $("llmStatus").textContent = data.timestamp || "";
      } catch (e) { $("status").textContent = e.message; }
      finally { busy(false); }
    };
    fetch("/api/health").then(r => r.json()).then(data => {
      $("topStatus").textContent = `data: ${data.data_root}`;
      $("health").textContent = `LLM: ${data.llm.config.model_name} | alive: ${data.llm.probe.alive}`;
    }).catch(() => { $("topStatus").textContent = "health unavailable"; });
    setInterval(() => {
      if (lastLoad) loadWorkspace({ silent: true });
    }, 60000);
  </script>
</body>
</html>
"""


class MMAIHandler(BaseHTTPRequestHandler):
    server_version = "MMAIWeb/1.0"

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"{self.address_string()} - {fmt % args}")

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, data: dict[str, Any], status: int = 200) -> None:
        self._send(status, json.dumps(data).encode("utf-8"), "application/json; charset=utf-8")

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or "0")
        if length > MAX_BODY_BYTES:
            raise ValueError("request body too large")
        raw = self.rfile.read(length) if length else b"{}"
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("json object required")
        return data

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/":
            self._send(200, INDEX_HTML.encode("utf-8"), "text/html; charset=utf-8")
            return
        if path == "/api/health":
            try:
                self._send_json(health_payload())
            except Exception as exc:  # noqa: BLE001
                self._send_json({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, 500)
            return
        self._send_json({"ok": False, "error": "not found"}, HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        try:
            payload = self._read_json()
            if path == "/api/load":
                self._send_json(load_workspace(payload))
                return
            if path == "/api/ask":
                self._send_json(ask_question(payload))
                return
            self._send_json({"ok": False, "error": "not found"}, HTTPStatus.NOT_FOUND)
        except Exception as exc:  # noqa: BLE001
            self._send_json({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, 500)


def serve(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> None:
    server = ThreadingHTTPServer((host, port), MMAIHandler)
    print(f"MM.AI web UI listening on http://{host}:{port}")
    print(f"Data root: {config.data_root()}")
    server.serve_forever()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="MM.AI web UI/API server")
    parser.add_argument("--host", default=os.environ.get("MM_AI_WEB_HOST", DEFAULT_HOST))
    parser.add_argument("--port", type=int, default=int(os.environ.get("MM_AI_WEB_PORT", DEFAULT_PORT)))
    args = parser.parse_args(argv)
    serve(args.host, args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
