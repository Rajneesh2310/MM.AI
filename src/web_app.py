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


def _format_card_value(value: Any) -> str:
    if value is None or value == "":
        return "Not Available"
    if isinstance(value, float):
        return f"{value:,.2f}"
    return str(value)


def _metric(label: str, value: Any, *, tone: str = "") -> str:
    css = f" metric-{tone}" if tone else ""
    return (
        f'<div class="metric{css}">'
        f"<span>{escape(label)}</span>"
        f"<strong>{escape(_format_card_value(value))}</strong>"
        "</div>"
    )


def _delta_tone(value: Any) -> str:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return ""
    if numeric > 0:
        return "up"
    if numeric < 0:
        return "down"
    return ""


def _has_segment_data(segment: dict[str, Any]) -> bool:
    return bool(segment.get("latest_session") or segment.get("latest_fo_row_count"))


def _market_cards_html(observations: list[dict[str, Any]]) -> str:
    if not observations:
        return '<div class="empty">No market data loaded.</div>'
    cards: list[str] = []
    for obs in observations:
        symbol = escape(str(obs.get("symbol") or "UNKNOWN"))
        cash = obs.get("cash") or {}
        fo = obs.get("fo") or {}
        cards.append(f'<article class="symbol-card"><header><h3>{symbol}</h3></header>')
        if _has_segment_data(cash):
            cards.append('<section class="segment-card"><h4>CASH</h4><div class="metric-grid">')
            cards.append(_metric("Latest session", cash.get("latest_session")))
            cards.append(_metric("Previous session", cash.get("previous_session")))
            cards.append(_metric("Close", cash.get("latest_close")))
            cards.append(_metric("Close change", cash.get("close_delta"), tone=_delta_tone(cash.get("close_delta"))))
            cards.append(_metric("Volume", cash.get("latest_volume")))
            cards.append(_metric("Volume change", cash.get("volume_delta"), tone=_delta_tone(cash.get("volume_delta"))))
            cards.append(_metric("Delivery qty", cash.get("latest_delivery_qty")))
            cards.append(_metric("Delivery %", cash.get("latest_delivery_percent")))
            cards.append("</div></section>")
        else:
            cards.append('<section class="segment-card"><h4>CASH</h4><div class="empty">Cash data not available.</div></section>')
        if _has_segment_data(fo):
            cards.append('<section class="segment-card"><h4>F&O</h4><div class="metric-grid">')
            cards.append(_metric("Latest session", fo.get("latest_session")))
            cards.append(_metric("Previous session", fo.get("previous_session")))
            cards.append(_metric("Rows", fo.get("latest_fo_row_count")))
            cards.append(_metric("Open interest", fo.get("latest_oi_total")))
            cards.append(_metric("OI change", fo.get("oi_delta"), tone=_delta_tone(fo.get("oi_delta"))))
            cards.append(_metric("Change in OI", fo.get("latest_chg_in_oi_total"), tone=_delta_tone(fo.get("latest_chg_in_oi_total"))))
            cards.append(_metric("Contracts", fo.get("latest_contracts_total")))
            cards.append(_metric("Contracts change", fo.get("contracts_delta"), tone=_delta_tone(fo.get("contracts_delta"))))
            cards.append("</div></section>")
        cards.append("</article>")
    return "".join(cards)


def _observation_html(observations: list[dict[str, Any]]) -> str:
    return _market_cards_html(observations)


def _news_html(results: list[NewsResult]) -> str:
    parts: list[str] = []
    for result in results:
        parts.append(f'<article class="news-group"><h3>{escape(result.symbol)}</h3>')
        if result.error:
            parts.append(f'<p class="error">ERROR: {escape(result.error)}</p>')
        if not result.items:
            parts.append('<p class="empty">No latest headlines available.</p></article>')
            continue
        parts.append('<ul class="news-list">')
        for item in result.items:
            headline = escape(item.headline or "Not Available")
            source = escape(item.source or "")
            url = escape(item.url or "", quote=True)
            published_at = escape(getattr(item, "published_at", "") or "publish date unavailable")
            if url:
                parts.append(f'<li><time>{published_at}</time><a href="{url}" target="_blank" rel="noreferrer">{headline}</a><small>{source}</small></li>')
            else:
                parts.append(f"<li><time>{published_at}</time><span>{headline}</span><small>{source}</small></li>")
        parts.append("</ul></article>")
    return "".join(parts) if parts else "<p>No news loaded.</p>"


def _news_query_for_symbol(symbol: str) -> str:
    return _NEWS_QUERIES.get(symbol.strip().upper(), symbol)


def _fetch_news_for_symbol(symbol: str, *, limit: int, timeout: float) -> NewsResult:
    result = fetch_symbol_news(_news_query_for_symbol(symbol), limit=limit, timeout=timeout)
    return replace(result, symbol=symbol)


def run_pipeline(
    symbols: list[str],
    *,
    lookback: int,
    news_limit: int,
    news_timeout: float,
) -> tuple[str, str, list[NewsResult], list[dict[str, Any]]]:
    observations = [_build_observations_for_symbol(sym, lookback) for sym in symbols]
    news_results = [
        _fetch_news_for_symbol(sym, limit=news_limit, timeout=news_timeout)
        for sym in symbols
    ]
    return _observation_html(observations), _news_html(news_results), news_results, observations


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

    obs_html, news_html, news_results, observations = run_pipeline(
        symbols,
        lookback=lookback,
        news_limit=news_limit,
        news_timeout=DEFAULT_TIMEOUT_SECONDS,
    )
    workspace_text = _workspace_text_for_symbols(symbols, lookback)
    data_inventory_html = _market_cards_html(observations)
    data_inventory_text = workspace_text
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


def build_prompt_response(payload: dict[str, Any], state: WebState = STATE) -> dict[str, Any]:
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
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "kind": "error",
            "timestamp": "",
            "error": f"{type(exc).__name__}: {exc}",
            "symbols": state.symbols,
            "prompt_text": state.prompt_text,
        }
    state.prompt_text = payload_obj.prompt_text
    return {
        "ok": True,
        "kind": "prompt",
        "timestamp": payload_obj.timestamp,
        "symbols": list(payload_obj.symbols),
        "prompt_text": payload_obj.prompt_text,
        "news_html": state.news_html,
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
        prompt_result = build_prompt_response(payload, state)
        if not prompt_result.get("ok"):
            return prompt_result
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
    :root { color-scheme: dark; --bg:#05080c; --panel:#0f141b; --panel2:#141b24; --line:#2a3544; --text:#eef3f8; --muted:#9fb0c2; --accent:#36d399; --warn:#f6c453; --bad:#ff6b6b; --blue:#75a7ff; }
    * { box-sizing: border-box; }
    body { margin:0; background:var(--bg); color:var(--text); font:14px/1.45 system-ui,Segoe UI,Arial,sans-serif; }
    header { display:flex; align-items:center; justify-content:space-between; padding:12px 18px; border-bottom:1px solid var(--line); background:#090e15; }
    h1 { margin:0; font-size:18px; letter-spacing:0; }
    main { display:grid; grid-template-columns:320px minmax(520px, 1.1fr) minmax(520px, .9fr); gap:12px; padding:12px; height:calc(100vh - 53px); }
    section, aside { background:var(--panel); border:1px solid var(--line); border-radius:8px; }
    aside { padding:14px; display:flex; flex-direction:column; gap:12px; }
    section { overflow:hidden; }
    .section-head { display:flex; align-items:center; justify-content:space-between; gap:10px; padding:10px 14px; border-bottom:1px solid var(--line); background:#111821; }
    .section-head h2 { margin:0; font-size:14px; text-transform:uppercase; color:#dfe8f2; }
    label { color:var(--muted); font-size:12px; display:block; margin-bottom:5px; }
    input, textarea, button { width:100%; border:1px solid var(--line); border-radius:6px; background:#080d13; color:var(--text); padding:10px; font:inherit; }
    textarea { min-height:155px; resize:vertical; }
    button { background:#123221; border-color:#1d6f45; cursor:pointer; font-weight:650; }
    button:disabled { opacity:.55; cursor:wait; }
    .row { display:grid; grid-template-columns:1fr 1fr; gap:10px; }
    .status { color:var(--muted); min-height:20px; }
    .panel-body { padding:12px; overflow:auto; height:calc(100vh - 107px); }
    .split { display:grid; gap:12px; }
    .block { border:1px solid var(--line); border-radius:8px; overflow:hidden; background:#080d13; }
    .block h3 { margin:0; padding:9px 11px; border-bottom:1px solid var(--line); background:#0b1017; font-size:13px; color:#d7e1ec; }
    .block-content { padding:10px; overflow:auto; }
    pre { white-space:pre-wrap; word-break:break-word; margin:0; color:var(--text); }
    .symbol-card { border:1px solid var(--line); border-radius:8px; background:#0b1118; margin-bottom:12px; overflow:hidden; }
    .symbol-card > header { padding:10px 12px; background:#121a24; border-bottom:1px solid var(--line); }
    .symbol-card h3 { margin:0; font-size:16px; color:#fff; }
    .segment-card { padding:12px; border-bottom:1px solid var(--line); }
    .segment-card:last-child { border-bottom:0; }
    .segment-card h4 { margin:0 0 9px; color:var(--blue); font-size:12px; letter-spacing:.08em; }
    .metric-grid { display:grid; grid-template-columns:repeat(2, minmax(0, 1fr)); gap:8px; }
    .metric { min-height:62px; border:1px solid #223044; border-radius:7px; background:var(--panel2); padding:8px; }
    .metric span { display:block; color:var(--muted); font-size:11px; margin-bottom:5px; }
    .metric strong { display:block; font-size:17px; color:#f8fbff; overflow-wrap:anywhere; }
    .metric-up strong { color:var(--accent); }
    .metric-down strong { color:var(--bad); }
    .empty { color:var(--muted); padding:8px 0; }
    .error { color:var(--bad); }
    .news-group { border-bottom:1px solid var(--line); padding:10px 0; }
    .news-group:first-child { padding-top:0; }
    .news-group h3 { margin:0 0 8px; color:#fff; }
    .news-list { list-style:none; margin:0; padding:0; display:grid; gap:8px; }
    .news-list li { display:grid; grid-template-columns:156px 1fr; gap:8px 10px; padding:8px; border:1px solid #223044; border-radius:7px; background:#101720; }
    .news-list time { color:var(--warn); font-size:12px; }
    .news-list a { color:#9eb4ff; }
    .news-list small { grid-column:2; color:var(--muted); }
    .answer { padding:12px; border:1px solid var(--line); border-radius:7px; background:#080d13; white-space:pre-wrap; min-height:205px; max-height:30vh; overflow:auto; }
    .prompt { padding:12px; border:1px solid var(--line); border-radius:7px; background:#080d13; white-space:pre-wrap; min-height:280px; max-height:38vh; overflow:auto; font-family:ui-monospace,Consolas,monospace; font-size:12px; color:#dce7f3; }
    .health { font-family:ui-monospace,Consolas,monospace; font-size:12px; color:var(--muted); white-space:pre-wrap; }
    @media (max-width: 1280px) { main { grid-template-columns:1fr; height:auto; } .panel-body { height:auto; max-height:72vh; } }
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
      <div class="section-head"><h2>Market Data Cards</h2><span id="symbolStatus" class="status"></span></div>
      <div class="panel-body split">
        <div id="inventory"><div class="empty">No market data loaded.</div></div>
      </div>
    </section>
    <section>
      <div class="section-head"><h2>AI Workbench</h2><span id="llmStatus" class="status"></span></div>
      <div class="panel-body split">
        <div class="block"><h3>LLM Output</h3><div id="answer" class="answer"></div></div>
        <div class="block"><h3>Prompt Sent To LLM</h3><pre id="prompt" class="prompt">Ask a question to build and display the exact prompt.</pre></div>
        <div class="block"><h3>News Ticker - Latest Published First</h3><div id="news" class="block-content"><div class="empty">No news loaded.</div></div></div>
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
      $("inventory").innerHTML = data.data_inventory_html || '<div class="empty">No market data loaded.</div>';
      $("news").innerHTML = data.news_html || "<pre>No news.</pre>";
      state.workspaceText = data.workspace_text || "";
      $("symbolStatus").textContent = (data.symbols || []).join(", ");
      $("prompt").textContent = "Ask a question to build and display the exact prompt.";
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
        const request = { ...payload(), question: $("question").value };
        const prepared = await post("/api/prompt", request);
        if (!prepared.ok) throw new Error(prepared.error || "prompt failed");
        $("prompt").textContent = prepared.prompt_text || "No prompt returned.";
        if (prepared.news_html) $("news").innerHTML = prepared.news_html;
        $("status").textContent = "Prompt ready. Waiting for LLM...";
        const data = await post("/api/ask", { question: $("question").value });
        $("answer").textContent = data.response_text || data.error || "";
        $("prompt").textContent = data.prompt_text || "No prompt returned.";
        if (data.news_html) $("news").innerHTML = data.news_html;
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
            if path == "/api/prompt":
                self._send_json(build_prompt_response(payload))
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
