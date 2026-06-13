"""Small browser UI/API for MM.AI on headless VPS deployments.

This module intentionally uses Python's standard-library HTTP server. It keeps
deployment simple: the existing MM.AI pipeline, local Ollama adapter, and
``/opt/mm-web-data`` default are reused without introducing another framework.
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from html import escape
from typing import Any
from urllib.parse import urlparse

from . import config, symbol_catalog
from .llm_adapter import generate_llm_response, probe_endpoint
from .llm_config import load_config_from_env
from .llm_prompt_builder import build_llm_prompt
from .news_fetcher import DEFAULT_TIMEOUT_SECONDS
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


@dataclass
class WebState:
    symbols: list[str] = field(default_factory=list)
    observation_html: str = ""
    news_html: str = ""
    workspace_text: str = ""
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
            obs = build_observations(load_symbol_data(sym, lookback_sessions=lookback))
            blocks.append(format_observations(obs))
        except Exception as exc:  # noqa: BLE001
            blocks.append(f"SYMBOL: {sym}\n(observation unavailable: {type(exc).__name__})\n")
    return "\n\n".join(blocks)


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
            if url:
                parts.append(f'<li><a href="{url}" target="_blank" rel="noreferrer">{headline}</a> <small>{source}</small></li>')
            else:
                parts.append(f"<li>{headline} <small>{source}</small></li>")
        parts.append("</ul>")
    return "".join(parts) if parts else "<p>No news loaded.</p>"


def run_pipeline(
    symbols: list[str],
    *,
    lookback: int,
    news_limit: int,
    news_timeout: float,
) -> tuple[str, str, list[NewsResult]]:
    observations = [_build_observations_for_symbol(sym, lookback) for sym in symbols]
    news_results = [
        fetch_symbol_news(sym, limit=news_limit, timeout=news_timeout)
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
    status = f"loaded {len(symbols)} symbol(s) - news: {sum(r.count for r in news_results)}"

    state.symbols = symbols
    state.observation_html = obs_html
    state.news_html = news_html
    state.workspace_text = workspace_text
    state.news_results = list(news_results)
    state.status = status

    return {
        "ok": True,
        "symbols": symbols,
        "status": status,
        "observation_html": obs_html,
        "news_html": news_html,
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
        response = generate_llm_response(payload_obj, load_config_from_env())
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "kind": "error",
            "timestamp": "",
            "response_text": f"{type(exc).__name__}: {exc}",
            "symbols": state.symbols,
        }
    kind = "ok" if response.ok else "error"
    text = response.response_text if response.ok else (response.error or "Market response unavailable.")
    return {
        "ok": response.ok,
        "kind": kind,
        "timestamp": response.timestamp,
        "response_text": text,
        "symbols": state.symbols,
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
    main { display:grid; grid-template-columns:minmax(320px, 420px) 1fr; gap:14px; padding:14px; min-height:calc(100vh - 55px); }
    section, aside { background:var(--panel); border:1px solid var(--line); border-radius:8px; }
    aside { padding:14px; display:flex; flex-direction:column; gap:12px; }
    label { color:var(--muted); font-size:12px; display:block; margin-bottom:5px; }
    input, textarea, button { width:100%; border:1px solid var(--line); border-radius:6px; background:#080d13; color:var(--text); padding:10px; font:inherit; }
    textarea { min-height:105px; resize:vertical; }
    button { background:#123221; border-color:#1d6f45; cursor:pointer; font-weight:650; }
    button:disabled { opacity:.55; cursor:wait; }
    .row { display:grid; grid-template-columns:1fr 1fr; gap:10px; }
    .status { color:var(--muted); min-height:20px; }
    .tabs { display:flex; border-bottom:1px solid var(--line); }
    .tab { width:auto; border:0; border-right:1px solid var(--line); border-radius:0; background:#0d131b; padding:10px 14px; }
    .tab.active { background:#182230; color:var(--accent); }
    .pane { display:none; padding:14px; overflow:auto; height:calc(100vh - 110px); }
    .pane.active { display:block; }
    pre { white-space:pre-wrap; word-break:break-word; margin:0; color:var(--text); }
    iframe { width:100%; height:100%; border:0; background:white; border-radius:6px; }
    .answer { padding:12px; border:1px solid var(--line); border-radius:6px; background:#080d13; white-space:pre-wrap; min-height:120px; }
    .health { font-family:ui-monospace,Consolas,monospace; font-size:12px; color:var(--muted); white-space:pre-wrap; }
    @media (max-width: 900px) { main { grid-template-columns:1fr; } .pane { height:55vh; } }
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
      <div id="answer" class="answer"></div>
      <div id="health" class="health"></div>
    </aside>
    <section>
      <div class="tabs">
        <button class="tab active" data-tab="obs">Observations</button>
        <button class="tab" data-tab="news">News</button>
        <button class="tab" data-tab="text">Workspace Text</button>
      </div>
      <div id="obs" class="pane active"><pre>No workspace loaded.</pre></div>
      <div id="news" class="pane"><pre>No news loaded.</pre></div>
      <div id="text" class="pane"><pre>No text loaded.</pre></div>
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
      $("obs").innerHTML = data.observation_html || "<pre>No observations.</pre>";
      $("news").innerHTML = data.news_html || "<pre>No news.</pre>";
      state.workspaceText = data.workspace_text || "";
      $("text").innerHTML = `<pre>${state.workspaceText.replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]))}</pre>`;
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
        $("status").textContent = `${data.kind || "response"} ${data.timestamp || ""}`;
      } catch (e) { $("status").textContent = e.message; }
      finally { busy(false); }
    };
    document.querySelectorAll(".tab").forEach(btn => btn.onclick = () => {
      document.querySelectorAll(".tab,.pane").forEach(el => el.classList.remove("active"));
      btn.classList.add("active"); $(btn.dataset.tab).classList.add("active");
    });
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
