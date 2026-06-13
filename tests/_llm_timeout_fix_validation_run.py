"""Live validation harness for the local-LLM timeout configuration fix.

Walks three knobs:

* **Default timeout** — with no env vars set, ``load_config_from_env()``
  must report ``timeout_seconds == 120.0``.
* **Env override** — ``MM_AI_LLM_TIMEOUT_SECONDS=180`` lifts the timeout
  to 180 s. ``MM_AI_LLM_TIMEOUT_SECONDS=abc`` is invalid and must fall
  back to 120 s without crashing.
* **End-to-end behaviour** — with the 120 s default and an alive local
  Ollama, a tiny ``/api/generate`` round-trip succeeds. With a forced
  ``socket.timeout`` the friendly translator renders
  ``"Local model request timed out after <N> seconds."``.

Output is a single UTF-8 JSON document written to the path in
``MM_AI_VALIDATION_OUT`` (falls back to stdout).
"""

from __future__ import annotations

import json
import os
import socket
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

from src.llm_adapter import generate_llm_response, probe_endpoint  # noqa: E402
from src.llm_config import (  # noqa: E402
    DEFAULT_TIMEOUT_SECONDS,
    ENV_BACKEND,
    ENV_ENDPOINT,
    ENV_MODEL,
    ENV_TIMEOUT,
    LLMConfig,
    MAX_TIMEOUT_SECONDS,
    MIN_TIMEOUT_SECONDS,
    load_config_from_env,
)
from src.llm_prompt_builder import build_llm_prompt  # noqa: E402
from src.talk_runner import _friendly_error_text  # noqa: E402

QUESTIONS = [
    "What changed in RELIANCE today?",
    "Compare RELIANCE and NIFTY.",
    "What changed in SBICARD today?",
]


def _scoped_env(values: dict[str, str | None]) -> dict[str, str | None]:
    """Snapshot current env for the keys we touch, apply ``values``, return
    the snapshot so the caller can restore."""
    keys = (ENV_BACKEND, ENV_MODEL, ENV_ENDPOINT, ENV_TIMEOUT)
    snapshot: dict[str, str | None] = {k: os.environ.get(k) for k in keys}
    for k in keys:
        os.environ.pop(k, None)
    for k, v in values.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    return snapshot


def _restore_env(snapshot: dict[str, str | None]) -> None:
    for k, v in snapshot.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


def _config_under(env_value: str | None) -> dict:
    """Return ``LLMConfig`` snapshot for the given ``MM_AI_LLM_TIMEOUT_SECONDS``."""
    snapshot = _scoped_env({ENV_TIMEOUT: env_value})
    try:
        cfg = load_config_from_env()
        out = {
            "env_value": env_value,
            "timeout_seconds": cfg.timeout_seconds,
            "model_name": cfg.model_name,
            "endpoint_url": cfg.endpoint_url,
        }
    except Exception as exc:  # noqa: BLE001
        out = {"env_value": env_value, "error": f"{type(exc).__name__}: {exc}"}
    finally:
        _restore_env(snapshot)
    return out


def _force_timeout_token(timeout_seconds: float) -> dict:
    """Drive the adapter with a forced ``socket.timeout`` to verify the
    token format and the friendly translation."""
    cfg = LLMConfig(
        "ollama",
        "qwen2.5:7b",
        "http://127.0.0.1:11434/api/generate",
        timeout_seconds,
    )
    payload = build_llm_prompt(
        "Diagnostic.",
        workspace_html=None,
        workspace_text="x",
        news_items=[],
        symbols=["DIAG"],
    )

    def slow(*_a, **_kw):
        raise socket.timeout("timed out")

    resp = generate_llm_response(payload, cfg, transport=slow)
    return {
        "config_timeout_seconds": cfg.timeout_seconds,
        "adapter_token": resp.error,
        "friendly_text": _friendly_error_text(resp),
        "ok": resp.ok,
    }


def _live_smoke(cfg: LLMConfig) -> dict:
    payload = build_llm_prompt(
        "OK",
        workspace_html=None,
        workspace_text="x",
        news_items=[],
        symbols=["X"],
    )
    resp = generate_llm_response(payload, cfg)
    return {
        "endpoint_used": cfg.endpoint_url,
        "model": cfg.model_name,
        "timeout_seconds": cfg.timeout_seconds,
        "ok": resp.ok,
        "elapsed_ms": resp.elapsed_ms,
        "prompt_chars": resp.prompt_chars,
        "adapter_token": resp.error,
        "friendly_text": _friendly_error_text(resp) if not resp.ok else None,
        "response_text_chars": len(resp.response_text or ""),
    }


def main() -> int:
    snapshot = _scoped_env({})
    try:
        default_cfg = load_config_from_env()
    finally:
        _restore_env(snapshot)

    env_matrix = [
        # (env value, expected_timeout_after_load)
        (None, 120.0),
        ("120", 120.0),
        ("180", 180.0),
        ("60", 60.0),
        ("abc", 120.0),
        ("", 120.0),
        ("not-a-number", 120.0),
        ("100000", MAX_TIMEOUT_SECONDS),
        ("0.0001", MIN_TIMEOUT_SECONDS),
        ("-30", MIN_TIMEOUT_SECONDS),
    ]
    env_results = []
    for raw, expected in env_matrix:
        info = _config_under(raw)
        info["expected_timeout_seconds"] = expected
        info["matches_expected"] = (
            "timeout_seconds" in info and info["timeout_seconds"] == expected
        )
        env_results.append(info)

    # Adapter token format under three representative timeouts.
    token_matrix = [_force_timeout_token(t) for t in (120.0, 180.0, 5.0, 89.6)]

    # Live smoke (only if Ollama is up). Uses the default-config so the
    # behaviour matches what the desktop app would see.
    probe_info = probe_endpoint(default_cfg, timeout=1.0)
    live_smoke: dict | None = None
    if probe_info.get("alive") and default_cfg.backend_type == "ollama":
        try:
            live_smoke = _live_smoke(default_cfg)
        except Exception as exc:  # noqa: BLE001
            live_smoke = {"harness_error": f"{type(exc).__name__}: {exc}"}

    out = {
        "constants": {
            "default_timeout_seconds": DEFAULT_TIMEOUT_SECONDS,
            "min_timeout_seconds": MIN_TIMEOUT_SECONDS,
            "max_timeout_seconds": MAX_TIMEOUT_SECONDS,
        },
        "default_config": {
            "backend_type": default_cfg.backend_type,
            "model_name": default_cfg.model_name,
            "endpoint_url": default_cfg.endpoint_url,
            "timeout_seconds": default_cfg.timeout_seconds,
        },
        "env_override_matrix": env_results,
        "adapter_token_matrix": token_matrix,
        "endpoint_probe": probe_info,
        "live_smoke": live_smoke,
        "questions_under_test": QUESTIONS,
    }

    payload_text = json.dumps(out, indent=2, ensure_ascii=False)
    target = os.environ.get("MM_AI_VALIDATION_OUT")
    if target:
        Path(target).write_text(payload_text, encoding="utf-8")
    else:
        sys.stdout.write(payload_text + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
