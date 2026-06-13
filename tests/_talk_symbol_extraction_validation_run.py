"""Live validation harness for the Talk-to-Market symbol-extraction flow.

Drives the deterministic ``extract_symbols_from_question`` extractor over
MM's real symbol catalogue (read-only) and walks the resulting symbols
through a headless ``MainWindow + WorkspaceController + TalkRunner``
stack with mocked I/O boundaries:

* ``fetch_symbol_news`` is replaced with an in-memory stub so no HTTP
  traffic is required.
* The local LLM transport is replaced with a fake that returns a
  deterministic ``{"response": "...""}`` Ollama-shaped dict — the safe
  prompt builder and the local LLM adapter both run end-to-end, the
  generation step itself is the only thing mocked.

Output is a single JSON document on stdout — consumed by
``MM.AI/talk-symbol-extraction-report.md``.
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import date
from pathlib import Path
from unittest.mock import patch

for _stream in (sys.stdout, sys.stderr):
    _reconfigure = getattr(_stream, "reconfigure", None)
    if callable(_reconfigure):
        try:
            _reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import polars as pl  # noqa: E402

from PySide6.QtWidgets import QApplication  # noqa: E402

from src import config, symbol_catalog  # noqa: E402
from src.llm_config import LLMConfig  # noqa: E402
from src.news_models import NewsItem, NewsResult  # noqa: E402
from src.symbol_extractor import extract_symbols_from_question  # noqa: E402
from src.talk_runner import (  # noqa: E402
    EMPTY_QUESTION_MESSAGE,
    NO_WORKSPACE_MESSAGE,
    TalkRunner,
)
from src.ui.main_window import MainWindow  # noqa: E402
from src.ui.theme import StatusState  # noqa: E402
from src.workspace_window import WorkspaceController  # noqa: E402


QUESTIONS = [
    "compare nifty and reliance",
    "What changed in RELIANCE today?",
    "Show INFY activity",
    "Why is NIFTY in news?",
    "compare reliance, infy and nifty",
    "compare reliance; infy; nifty",
    "what changed today?",
    "   ",  # whitespace-only -> empty
]


def _stub_news(symbol: str, **_kw) -> NewsResult:
    return NewsResult(
        symbol=symbol,
        timestamp="25:05:26 14:00:00",
        count=1,
        items=[
            NewsItem(
                headline=f"{symbol} headline alpha",
                source="WireTest",
                url=f"https://news.example/{symbol.lower()}-1",
                timestamp="25:05:26 14:00:00",
            )
        ],
        source_query_url=f"https://news.example/rss?q={symbol}",
    )


def _local_cfg() -> LLMConfig:
    return LLMConfig(
        "ollama", "mock-model", "http://127.0.0.1:11434/api/generate", 5.0
    )


def _spin_until(qapp, predicate, timeout_ms: int = 8000) -> bool:
    deadline = time.monotonic() + (timeout_ms / 1000.0)
    while time.monotonic() < deadline:
        qapp.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    qapp.processEvents()
    return bool(predicate())


def _drain_threads(qapp, controller, timeout_ms: int = 4000) -> None:
    runner = controller.talk_runner()
    deadline = time.monotonic() + (timeout_ms / 1000.0)
    while time.monotonic() < deadline:
        qapp.processEvents()
        if controller._thread is None and runner._thread is None:
            return
        time.sleep(0.01)
    qapp.processEvents()


def _exercise_extractor() -> list[dict]:
    """Pass each spec question through the deterministic extractor."""
    universe = symbol_catalog.list_all_symbols()
    out: list[dict] = []
    for q in QUESTIONS:
        # Two variants:
        #  1. Restricted to MM's live universe.
        #  2. Safe fallback only (no catalogue supplied).
        out.append(
            {
                "question": q,
                "extracted_with_full_universe": extract_symbols_from_question(
                    q, known_symbols=universe
                ),
                "extracted_safe_fallback": extract_symbols_from_question(q),
            }
        )
    return out


def _run_ui_chain(qapp, question: str, captured_transport_bodies: list) -> dict:
    """Drive the full Talk-to-Market UX once for ``question``."""

    def transport(url, body, timeout):
        captured_transport_bodies.append({"url": url, "body": body})
        return {"response": "OK: deterministic test reply."}

    window = MainWindow()
    runner = TalkRunner(parent=window, config=_local_cfg(), transport=transport)
    controller = WorkspaceController(window, talk_runner=runner)

    statuses: list[str] = []
    orig = window.set_status_state

    def spy_state(state, message=None, *, header_override=None):
        statuses.append(header_override if header_override is not None else state)
        orig(state, message, header_override=header_override)

    window.set_status_state = spy_state  # type: ignore[assignment]

    ok_hits: list[tuple[str, str]] = []
    err_hits: list[tuple[str, str]] = []
    runner.finished_ok.connect(lambda t, s: ok_hits.append((t, s)))
    runner.finished_error.connect(lambda t, s: err_hits.append((t, s)))

    with patch(
        "src.workspace_window.fetch_symbol_news",
        side_effect=lambda s, **kw: _stub_news(s),
    ):
        controller._on_talk_requested(question)
        _spin_until(
            qapp,
            lambda: bool(ok_hits) or bool(err_hits),
            timeout_ms=10_000,
        )
    _drain_threads(qapp, controller)

    out = {
        "question": question,
        "loaded_symbols": list(controller._last_symbols),
        "symbol_field_text": window.symbol_field().text(),
        "ok_hits": [list(x) for x in ok_hits],
        "err_hits": [list(x) for x in err_hits],
        "status_transitions": statuses,
        "observation_has_text": bool(window.observation_plain_text().strip()),
        "news_html_chars": len(window.news_html() or ""),
        "no_workspace_fallback_in_response": any(
            t == NO_WORKSPACE_MESSAGE for t, _ in ok_hits
        ),
        "empty_question_fallback_in_response": any(
            t == EMPTY_QUESTION_MESSAGE for t, _ in err_hits
        ),
    }
    window.close()
    qapp.processEvents()
    return out


def _setup_fake_install(root: Path) -> None:
    """Write JSON catalogue + minimal parquet so the pipeline can load."""
    os.environ["MM_INSTALL_ROOT"] = str(root)
    (root / "data").mkdir(exist_ok=True)
    (root / "data" / "cash_symbols.json").write_text(
        json.dumps(["RELIANCE", "INFY", "TCS"]), encoding="utf-8"
    )
    (root / "data" / "fo_symbols.json").write_text(
        json.dumps(["NIFTY", "BANKNIFTY", "RELIANCE", "INFY"]),
        encoding="utf-8",
    )

    def _row(d: date, close: float, sym: str) -> dict:
        return {
            "SYMBOL": sym,
            "DATE": d,
            "OPEN": close - 1.0,
            "HIGH": close + 1.0,
            "LOW": close - 1.5,
            "CLOSE": close,
            "VOLUME": 1000.0,
            "TURNOVER": close * 1000.0,
            "DELIVERY_QTY": None,
            "DELIVERY_PERCENT": None,
        }

    def _write_cash(symbol: str, closes: list[tuple[date, float]]) -> None:
        sym_dir = root / "data" / "cash" / f"SYMBOL={symbol}"
        sym_dir.mkdir(parents=True, exist_ok=True)
        rows = [_row(d, c, symbol) for d, c in closes]
        df = (
            pl.DataFrame(rows)
            .with_columns(
                pl.lit(rows[0]["DATE"].year).cast(pl.Int32).alias("YEAR")
            )
        )
        df.write_parquet(sym_dir / f"YEAR={rows[0]['DATE'].year}.parquet")

    for sym, val in [("RELIANCE", 1359.7), ("INFY", 1193.7), ("NIFTY", 24700.0)]:
        _write_cash(
            sym, [(date(2026, 5, 19), val - 30.0), (date(2026, 5, 20), val)]
        )

    symbol_catalog.clear_cache()


def main() -> int:
    # Use a sandbox install so we never need to touch real parquet data.
    sandbox = Path(os.environ.get("TEMP", ".")) / "mm_ai_talk_extract_validation"
    sandbox.mkdir(parents=True, exist_ok=True)
    for p in (sandbox / "data" / "cash").glob("**/*.parquet"):
        try:
            p.unlink()
        except OSError:
            pass
    _setup_fake_install(sandbox)

    extractor_results = _exercise_extractor()

    app = QApplication.instance() or QApplication(sys.argv)

    captured_bodies: list[dict] = []
    ui_results: list[dict] = []
    for q in QUESTIONS:
        ui_results.append(_run_ui_chain(app, q, captured_bodies))

    # Prompt-builder sanity: every body sent to the transport must contain
    # all five canonical safe-prompt sections, and HTML must never leak.
    prompt_sections = ("SYSTEM RULES", "USER QUESTION", "OBSERVABLE MARKET DATA",
                       "NEWS HEADLINES", "RESPONSE CONSTRAINTS")
    safe_prompt_audit = []
    for entry in captured_bodies:
        body = entry["body"]
        prompt = body.get("prompt", "")
        safe_prompt_audit.append(
            {
                "all_sections_present": all(s in prompt for s in prompt_sections),
                "has_html_leak": "<html" in prompt.lower()
                or "<p>" in prompt
                or "<div" in prompt,
                "prompt_chars": len(prompt),
            }
        )

    out = {
        "install_root": str(config.install_root()),
        "extractor_validation": extractor_results,
        "ui_validation": ui_results,
        "llm_transport_called_times": len(captured_bodies),
        "safe_prompt_audit": safe_prompt_audit,
        "status_state_tokens_seen": sorted(
            {s for r in ui_results for s in r["status_transitions"]}
        ),
    }
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
