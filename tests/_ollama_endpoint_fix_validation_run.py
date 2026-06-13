"""Live validation harness for the Ollama endpoint configuration fix.

Behaviour:

* TCP-probes ``http://localhost:11434`` to detect whether Ollama is
  actually running locally.
* When **alive**: issues a tiny ``/api/generate`` POST with
  ``model="qwen2.5:7b"`` and a deterministic placeholder prompt to make
  sure the canonical endpoint + body shape elicit ``ok=True``. The
  ``response_text`` is **not** displayed (no market interpretation).
* When **down**: replaces the adapter transport with a deterministic
  stub so the full Talk-to-Market pipeline (build_llm_prompt ->
  generate_llm_response -> TalkRunner.ask_sync) can still be exercised
  with each spec validation case.
* Walks the four required questions through TalkRunner.ask_sync for
  RELIANCE / INFY / SBICARD / NIFTY, captures the ``(kind, friendly_text)``
  the response panel would render.
* Also surfaces each backend error mode (timeout, connection refused,
  http 404 with model-not-found body, http 500) translated through
  ``_friendly_error_text`` so the report can show side-by-side adapter
  tokens vs spec wording.

Output is a single JSON document on stdout — consumed by
``MM.AI/ollama-endpoint-fix-report.md``.
"""

from __future__ import annotations

import json
import os
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

from src.llm_adapter import (  # noqa: E402
    _is_local_endpoint,
    generate_llm_response,
    normalise_ollama_endpoint,
    probe_endpoint,
)
from src.llm_config import (  # noqa: E402
    DEFAULT_ENDPOINTS,
    DEFAULT_MODELS,
    LLMConfig,
    load_config_from_env,
)
from src.llm_models import LLMPromptPayload  # noqa: E402
from src.llm_prompt_builder import build_llm_prompt  # noqa: E402
from src.news_models import NewsItem, NewsResult  # noqa: E402
from src.talk_runner import (  # noqa: E402
    TalkRunner,
    _friendly_error_text,
)


SYMBOLS = ["RELIANCE", "INFY", "SBICARD", "NIFTY"]
QUESTIONS = [
    "What changed in RELIANCE today?",
    "Compare RELIANCE and INFY.",
    "Why is NIFTY in news?",
    "What changed in SBICARD today?",
]


def _is_live(endpoint: str, timeout: float = 1.0) -> tuple[bool, dict]:
    """Return ``(alive, probe_info)`` for the *normalised* endpoint."""
    cfg = LLMConfig("ollama", "qwen2.5:7b", endpoint, timeout)
    info = probe_endpoint(cfg, timeout=timeout)
    return bool(info.get("alive")), info


def _fake_news(symbol: str) -> NewsResult:
    return NewsResult(
        symbol=symbol,
        timestamp="25:05:26 15:00:00",
        count=1,
        items=[
            NewsItem(
                headline=f"{symbol} headline alpha",
                source="WireTest",
                url=f"https://news.example/{symbol.lower()}-1",
                timestamp="25:05:26 15:00:00",
            )
        ],
        source_query_url=f"https://news.example/rss?q={symbol}",
    )


def _fake_workspace_text() -> str:
    return (
        "SYMBOL: RELIANCE\n\nCASH\nLatest Close:\n1359.7\nClose Delta:\n37.0\n"
    )


def _build_one(question: str) -> LLMPromptPayload:
    return build_llm_prompt(
        question,
        workspace_html=None,
        workspace_text=_fake_workspace_text(),
        news_items=[_fake_news(s) for s in SYMBOLS],
        symbols=SYMBOLS,
    )


# ---------------------------------------------------------------------------
# Live or mocked Talk-to-Market round-trips
# ---------------------------------------------------------------------------


def _live_smoke(cfg: LLMConfig) -> dict:
    """Tiny /api/generate round-trip used solely to confirm that the
    canonical endpoint + body shape elicits a successful HTTP response
    (i.e. no more ``http_error: 404 Not Found``). The prompt is the
    smallest one the safe prompt builder will accept."""
    smoke_cfg = LLMConfig(
        cfg.backend_type,
        cfg.model_name,
        cfg.endpoint_url,
        max(cfg.timeout_seconds, 120.0),
    )
    payload = build_llm_prompt(
        "OK",
        workspace_html=None,
        workspace_text="x",
        news_items=[],
        symbols=["X"],
    )
    resp = generate_llm_response(payload, smoke_cfg)
    return {
        "endpoint_used": smoke_cfg.endpoint_url,
        "model": smoke_cfg.model_name,
        "timeout_seconds": smoke_cfg.timeout_seconds,
        "ok": resp.ok,
        "elapsed_ms": resp.elapsed_ms,
        "prompt_chars": resp.prompt_chars,
        "adapter_token": resp.error,
        "friendly_text": _friendly_error_text(resp) if not resp.ok else None,
        "response_was_non_empty": bool(resp.response_text),
        # We never echo the model output verbatim; only its length.
        "response_text_chars": len(resp.response_text or ""),
    }


def _mocked_runs(cfg: LLMConfig) -> list[dict]:
    """Same flow with a deterministic transport so the report has data
    even when Ollama is not running on this machine."""

    def transport(url, body, timeout):
        return {"response": "MOCK_OK"}

    out: list[dict] = []
    runner = TalkRunner(config=cfg, transport=transport)
    runner.set_workspace(
        _fake_workspace_text(), None, [_fake_news(s) for s in SYMBOLS], SYMBOLS
    )
    for q in QUESTIONS:
        kind, text, ts = runner.ask_sync(q)
        out.append(
            {
                "question": q,
                "kind": kind,
                "timestamp": ts,
                "response_was_non_empty": bool(text),
            }
        )
    return out


# ---------------------------------------------------------------------------
# Error-mode coverage (deterministic, no network)
# ---------------------------------------------------------------------------


def _error_mode_matrix(cfg: LLMConfig) -> list[dict]:
    """Drive each adapter failure path through a mocked transport and
    capture both the adapter's internal token AND the friendly string
    shown to the user."""
    payload = _build_one("Diagnostic.")
    matrix: list[dict] = []

    def _row(label: str, raise_exc=None, return_value=None):
        def transport(*_a, **_kw):
            if raise_exc is not None:
                raise raise_exc()
            return return_value

        resp = generate_llm_response(payload, cfg, transport=transport)
        return {
            "case": label,
            "adapter_token": resp.error,
            "friendly_text": _friendly_error_text(resp),
        }

    matrix.append(_row("timeout", raise_exc=lambda: socket.timeout("timed out")))
    matrix.append(
        _row(
            "connection_refused",
            raise_exc=lambda: urllib.error.URLError("Connection refused"),
        )
    )

    class _HTTP404(urllib.error.HTTPError):
        def __init__(self):
            super().__init__(
                cfg.endpoint_url, 404, "Not Found", {}, None  # type: ignore[arg-type]
            )

        def read(self):  # type: ignore[override]
            return (
                b'{"error": "model \\"missing-model\\" not found, '
                b'try pulling it first"}'
            )

    matrix.append(_row("http_404_model_missing", raise_exc=_HTTP404))

    class _HTTP500(urllib.error.HTTPError):
        def __init__(self):
            super().__init__(
                cfg.endpoint_url, 500, "Internal Server Error", {}, None  # type: ignore[arg-type]
            )

        def read(self):  # type: ignore[override]
            return b""

    matrix.append(_row("http_500", raise_exc=_HTTP500))

    matrix.append(
        _row(
            "endpoint_rejected",
            raise_exc=None,
            return_value={"response": "MOCK"},
        )
    )

    return matrix


def main() -> int:
    canonical_endpoint = "http://localhost:11434/api/generate"

    # Normalisation matrix — eight representative inputs.
    normalisation_cases = [
        canonical_endpoint,
        "http://localhost:11434",
        "http://localhost:11434/",
        "http://localhost:11434/v1/chat/completions",
        "http://localhost:11434/api/chat",
        "http://127.0.0.1:11434/foo",
        "https://127.0.0.1:11434/",
        "http://localhost:11434/api/generate?stream=true#hash",
    ]
    normalisation_report = [
        {"input": u, "normalised": normalise_ollama_endpoint(u)}
        for u in normalisation_cases
    ]

    env_cfg = load_config_from_env()
    is_alive, probe_info = _is_live(env_cfg.endpoint_url)
    live_smoke: dict | None = None
    mocked_runs: list[dict] = []

    if is_alive and env_cfg.backend_type == "ollama":
        try:
            live_smoke = _live_smoke(env_cfg)
        except Exception as exc:  # noqa: BLE001
            live_smoke = {"harness_error": f"{type(exc).__name__}: {exc}"}
    mocked_runs = _mocked_runs(env_cfg)

    # Error-mode matrix uses a config aimed at the canonical local
    # endpoint regardless of whether the runtime is alive, so the
    # `_is_local_endpoint` guard is satisfied.
    diag_cfg = LLMConfig(
        "ollama", env_cfg.model_name or "qwen2.5:7b",
        canonical_endpoint, env_cfg.timeout_seconds,
    )
    error_matrix = _error_mode_matrix(diag_cfg)

    # Tweak the endpoint_rejected row to actually hit a non-local endpoint.
    public_cfg = LLMConfig(
        "ollama", "qwen2.5:7b", "http://8.8.8.8/api/generate", 1.0
    )
    rejected = generate_llm_response(
        _build_one("Diagnostic."), public_cfg, transport=lambda *_a, **_kw: {}
    )
    for row in error_matrix:
        if row["case"] == "endpoint_rejected":
            row["adapter_token"] = rejected.error
            row["friendly_text"] = _friendly_error_text(rejected)
            break

    out = {
        "config": {
            "backend_type": env_cfg.backend_type,
            "model_name": env_cfg.model_name,
            "endpoint_url": env_cfg.endpoint_url,
            "endpoint_after_normalise": normalise_ollama_endpoint(
                env_cfg.endpoint_url
            ),
            "timeout_seconds": env_cfg.timeout_seconds,
        },
        "defaults": {
            "ollama_default_model": DEFAULT_MODELS["ollama"],
            "ollama_default_endpoint": DEFAULT_ENDPOINTS["ollama"],
        },
        "local_endpoint_guard": {
            "ok": _is_local_endpoint(canonical_endpoint)[0],
            "reason": _is_local_endpoint(canonical_endpoint)[1],
        },
        "endpoint_probe": {
            "endpoint": env_cfg.endpoint_url,
            "alive": is_alive,
            "info": probe_info,
        },
        "endpoint_normalisation": normalisation_report,
        "live_smoke": live_smoke,
        "mocked_runs": mocked_runs,
        "error_mode_matrix": error_matrix,
        "symbols_under_test": SYMBOLS,
        "questions_under_test": QUESTIONS,
    }
    # Use sys.stdout.write with explicit utf-8 so the report file is not
    # tainted by Windows-default code pages or PowerShell's UTF-16 pipe.
    payload_text = json.dumps(out, indent=2, ensure_ascii=False)
    out_path = os.environ.get("MM_AI_VALIDATION_OUT")
    if out_path:
        Path(out_path).write_text(payload_text, encoding="utf-8")
    else:
        sys.stdout.write(payload_text)
        sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
