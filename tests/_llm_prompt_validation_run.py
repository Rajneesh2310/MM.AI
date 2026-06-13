"""Headless validation harness for the LLM prompt-builder.

Drives ``build_llm_prompt`` against live MM parquet + live RSS for the four
required validation questions and prints a factual JSON summary. The output
is consumed by ``MM.AI/llm-prompt-builder-report.md``.

The script never calls an LLM. It only verifies that the payload contract
holds end-to-end: section presence, immutable rules, forbidden-phrase
guard, timestamp format, sanitiser behaviour, and field redaction.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    _reconfigure = getattr(_stream, "reconfigure", None)
    if callable(_reconfigure):
        try:
            _reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.llm_models import (
    FORBIDDEN_OUTPUT_PHRASES,
    RESPONSE_CONSTRAINTS_ALLOWED,
    RESPONSE_CONSTRAINTS_FORBIDDEN,
    SYSTEM_RULES,
)
from src.llm_prompt_builder import build_llm_prompt
from src.news_fetcher import fetch_symbol_news
from src.observation_builder import build_observations
from src.symbol_reader import load_symbol_data
from src.text_formatter import format_observations

TIMESTAMP_RE = re.compile(r"^\d{2}:\d{2}:\d{2} \d{2}:\d{2}:\d{2}$")

CASES = [
    ("What changed in RELIANCE today?", ["RELIANCE"]),
    ("Compare RELIANCE and INFY.", ["RELIANCE", "INFY"]),
    ("Why is NIFTY in news?", ["NIFTY"]),
    ("Show INFY activity.", ["INFY"]),
]


def _build_workspace_text(symbol: str) -> str:
    try:
        sd = load_symbol_data(symbol, lookback_sessions=5)
        return format_observations(build_observations(sd))
    except Exception as exc:  # noqa: BLE001
        return f"[error] {type(exc).__name__}: {exc}\n"


def _grade(payload, news_items, workspace_text_inputs) -> dict:
    pt = payload.prompt_text
    section_hits = {
        title: bool(
            re.search(rf"={{60}}\n{re.escape(title)}\n={{60}}", pt)
        )
        for title in [
            "SYSTEM RULES",
            "USER QUESTION",
            "OBSERVABLE MARKET DATA",
            "NEWS HEADLINES",
            "RESPONSE CONSTRAINTS",
        ]
    }
    rules_hit = {rule: (rule in pt) for rule in SYSTEM_RULES}
    allowed_hit = {tok: (tok in pt) for tok in RESPONSE_CONSTRAINTS_ALLOWED}
    forbidden_hit = {tok: (tok in pt) for tok in RESPONSE_CONSTRAINTS_FORBIDDEN}
    user_blob = (
        payload.question
        + "\n"
        + "\n".join(workspace_text_inputs)
        + "\n"
        + "\n".join((it.headline or "") for it in news_items)
        + "\n"
        + "\n".join((it.source or "") for it in news_items)
    ).lower()
    forbidden_phrase_in_user_inputs = {
        p: (p in user_blob) for p in FORBIDDEN_OUTPUT_PHRASES
    }
    return {
        "section_present": section_hits,
        "all_sections_present": all(section_hits.values()),
        "system_rules_all_present": all(rules_hit.values()),
        "missing_rules": [r for r, ok in rules_hit.items() if not ok],
        "allowed_constraints_all_present": all(allowed_hit.values()),
        "forbidden_constraint_labels_all_present": all(forbidden_hit.values()),
        "timestamp_format_ok": bool(TIMESTAMP_RE.match(payload.timestamp)),
        "fallback_reply_string_present": (
            '"I do not have enough observable data to answer that."' in pt
        ),
        "parquet_path_leaked": ".parquet" in pt
        or "MMMarket" in pt
        or "C:\\" in pt,
        "html_tags_leaked": "<table" in pt or "<div" in pt,
        "traceback_leaked": "Traceback (most recent call last)" in pt,
        "forbidden_phrase_in_user_inputs": forbidden_phrase_in_user_inputs,
        "any_forbidden_in_user_inputs": any(forbidden_phrase_in_user_inputs.values()),
        "prompt_text_chars": len(pt),
    }


def main() -> int:
    rows: list[dict] = []
    for question, symbols in CASES:
        workspace_pieces = [_build_workspace_text(s) for s in symbols]
        workspace_text = "\n\n".join(workspace_pieces)
        flat_items = []
        for s in symbols:
            try:
                result = fetch_symbol_news(s, limit=5, timeout=8.0)
                flat_items.extend(result.items)
            except Exception:  # noqa: BLE001
                pass
        try:
            payload = build_llm_prompt(
                question,
                None,
                workspace_text,
                flat_items,
                symbols,
            )
            error = None
            grade = _grade(payload, flat_items, workspace_pieces)
        except Exception as exc:  # noqa: BLE001
            error = f"{type(exc).__name__}: {exc}"
            payload = None
            grade = None
        rows.append(
            {
                "question": question,
                "symbols": symbols,
                "news_item_count": len(flat_items),
                "error": error,
                "timestamp": payload.timestamp if payload else None,
                "prompt_chars": len(payload.prompt_text) if payload else 0,
                "grade": grade,
            }
        )

    # Negative case — caller injects a forbidden phrase
    negative = {
        "case": "forbidden_phrase_in_question",
        "input": "Give me a guaranteed buy signal for RELIANCE.",
        "raised": False,
        "error": None,
    }
    try:
        build_llm_prompt(
            negative["input"], None, "", [], ["RELIANCE"]
        )
    except ValueError as exc:
        negative["raised"] = True
        negative["error"] = str(exc)
    rows.append(negative)

    print(json.dumps(rows, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
