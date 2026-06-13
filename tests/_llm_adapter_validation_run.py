"""Headless validation harness for the local-LLM adapter.

Strategy per question (3 required questions):
1. Build a safe prompt payload via :func:`build_llm_prompt` using live MM
   parquet + live RSS headlines.
2. Probe the local Ollama endpoint. If reachable, drive ``generate_llm_response``
   over the live runtime.
3. Always also drive both backends (ollama + openai_compatible) through a
   deterministic *mocked* transport, so the report can show end-to-end
   adapter behaviour even on machines without a local LLM running.
4. Also exercise every documented error mode (timeout, connection failure,
   malformed JSON, missing fields, public endpoint blocked).

The harness never calls a cloud API and never invokes a real LLM unless the
*local* Ollama endpoint is reachable. Output is a JSON-line report on stdout.
"""

from __future__ import annotations

import json
import socket
import sys
import urllib.error
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

from src.llm_adapter import generate_llm_response, probe_endpoint
from src.llm_config import LLMConfig, load_config_from_env
from src.llm_prompt_builder import build_llm_prompt
from src.news_fetcher import fetch_symbol_news
from src.observation_builder import build_observations
from src.symbol_reader import load_symbol_data
from src.text_formatter import format_observations

QUESTIONS: list[tuple[str, list[str]]] = [
    ("What changed in RELIANCE today?", ["RELIANCE"]),
    ("Compare RELIANCE and INFY.", ["RELIANCE", "INFY"]),
    ("Why is NIFTY in news?", ["NIFTY"]),
]


def _safe_workspace_text(symbol: str) -> str:
    try:
        sd = load_symbol_data(symbol, lookback_sessions=5)
        return format_observations(build_observations(sd))
    except Exception as exc:  # noqa: BLE001
        return f"[error] {type(exc).__name__}: {exc}\n"


def _safe_news(symbol: str, limit: int = 3) -> list:
    try:
        return list(fetch_symbol_news(symbol, limit=limit, timeout=6.0).items)
    except Exception:  # noqa: BLE001
        return []


def _make_payload(question: str, symbols: list[str]):
    workspace_text = "\n\n".join(_safe_workspace_text(s) for s in symbols)
    news_items: list = []
    for s in symbols:
        news_items.extend(_safe_news(s))
    return build_llm_prompt(
        question, None, workspace_text, news_items, symbols
    )


def _mock_ollama_transport(canned_text: str):
    def transport(url, body, timeout):
        return {
            "model": body.get("model", "mock"),
            "response": canned_text,
            "done": True,
        }

    return transport


def _mock_openai_transport(canned_text: str):
    def transport(url, body, timeout):
        return {
            "choices": [
                {"message": {"role": "assistant", "content": canned_text}}
            ]
        }

    return transport


def _scenario_row(
    label: str, response, *, expected_ok: bool, extra: dict | None = None
) -> dict:
    return {
        "scenario": label,
        "expected_ok": expected_ok,
        "actual_ok": response.ok,
        "matches_expectation": response.ok == expected_ok,
        "backend": response.backend,
        "model": response.model,
        "endpoint": response.endpoint,
        "timestamp": response.timestamp,
        "error": response.error,
        "elapsed_ms": response.elapsed_ms,
        "prompt_chars": response.prompt_chars,
        "response_chars": len(response.response_text),
        **(extra or {}),
    }


def main() -> int:
    base_cfg = load_config_from_env()
    probe = probe_endpoint(base_cfg, timeout=1.5)

    questions_block: list[dict] = []
    for question, symbols in QUESTIONS:
        payload = _make_payload(question, symbols)
        per_question: dict = {
            "question": question,
            "symbols": symbols,
            "prompt_chars": len(payload.prompt_text),
            "runs": [],
        }

        # 1. Mocked Ollama
        cfg_ollama_mock = LLMConfig(
            "ollama", "mock-llama", "http://127.0.0.1:11434/api/generate", 5.0
        )
        resp = generate_llm_response(
            payload,
            cfg_ollama_mock,
            transport=_mock_ollama_transport(
                "Mocked plain-text response for: " + question
            ),
        )
        per_question["runs"].append(
            _scenario_row("mocked_ollama", resp, expected_ok=True)
        )

        # 2. Mocked OpenAI-compatible
        cfg_openai_mock = LLMConfig(
            "openai_compatible",
            "mock-local",
            "http://127.0.0.1:8000/v1/chat/completions",
            5.0,
        )
        resp = generate_llm_response(
            payload,
            cfg_openai_mock,
            transport=_mock_openai_transport(
                "Mocked OpenAI-compat response for: " + question
            ),
        )
        per_question["runs"].append(
            _scenario_row("mocked_openai_compatible", resp, expected_ok=True)
        )

        # 3. Live Ollama if probe succeeded
        if probe["alive"]:
            resp = generate_llm_response(payload, base_cfg)
            per_question["runs"].append(
                _scenario_row("live_ollama", resp, expected_ok=resp.ok)
            )

        questions_block.append(per_question)

    # Negative scenarios exercised once each.
    negatives: list[dict] = []

    cfg = LLMConfig("ollama", "x", "http://127.0.0.1:11434/api/generate", 5.0)
    sample = _make_payload("What changed in RELIANCE today?", ["RELIANCE"])

    def t_timeout(*_a, **_kw):
        raise socket.timeout("timed out")

    negatives.append(
        _scenario_row(
            "timeout",
            generate_llm_response(sample, cfg, transport=t_timeout),
            expected_ok=False,
            extra={"expected_error": "timeout"},
        )
    )

    def t_conn(*_a, **_kw):
        raise urllib.error.URLError("Connection refused")

    negatives.append(
        _scenario_row(
            "connection_failure",
            generate_llm_response(sample, cfg, transport=t_conn),
            expected_ok=False,
            extra={"expected_error_fragment": "connection_failure"},
        )
    )

    def t_bad_json(*_a, **_kw):
        raise json.JSONDecodeError("expected value", "doc", 0)

    negatives.append(
        _scenario_row(
            "invalid_json",
            generate_llm_response(sample, cfg, transport=t_bad_json),
            expected_ok=False,
            extra={"expected_error_fragment": "invalid_json"},
        )
    )

    def t_no_resp(*_a, **_kw):
        return {"done": True}

    negatives.append(
        _scenario_row(
            "malformed_response_missing_field",
            generate_llm_response(sample, cfg, transport=t_no_resp),
            expected_ok=False,
            extra={"expected_error_fragment": "missing_response_field"},
        )
    )

    cfg_public = LLMConfig(
        "openai_compatible",
        "x",
        "http://8.8.8.8/v1/chat/completions",
        5.0,
    )

    def must_not_call(*_a, **_kw):
        raise AssertionError("transport should not be called")

    negatives.append(
        _scenario_row(
            "public_endpoint_blocked",
            generate_llm_response(sample, cfg_public, transport=must_not_call),
            expected_ok=False,
            extra={"expected_error_fragment": "endpoint_rejected"},
        )
    )

    out = {
        "config": base_cfg.as_dict(),
        "probe": probe,
        "questions": questions_block,
        "negative_scenarios": negatives,
    }
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
