"""Configuration for the MM.AI local-LLM adapter.

The adapter only talks to a local runtime (Ollama or any OpenAI-compatible
local server). Configuration is read from environment variables so the same
binary can be pointed at different local runtimes without code changes.

Environment variables:
- ``MM_AI_LLM_BACKEND``          ``ollama`` (default) | ``openai_compatible`` | ``openrouter``
- ``MM_AI_LLM_MODEL``            model name (defaults per-backend)
- ``MM_AI_LLM_ENDPOINT``         POST URL (defaults per-backend)
- ``MM_AI_LLM_TIMEOUT_SECONDS``  request timeout, clamped to [1, 600]
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

SUPPORTED_BACKENDS: tuple[str, ...] = ("ollama", "openai_compatible", "openrouter")

ENV_BACKEND = "MM_AI_LLM_BACKEND"
ENV_MODEL = "MM_AI_LLM_MODEL"
ENV_ENDPOINT = "MM_AI_LLM_ENDPOINT"
ENV_TIMEOUT = "MM_AI_LLM_TIMEOUT_SECONDS"

# Endpoint + model defaults per backend. These are *examples* — the user is
# expected to set the env vars when their local runtime differs.
DEFAULT_ENDPOINTS: dict[str, str] = {
    "ollama": "http://localhost:11434/api/generate",
    "openai_compatible": "http://localhost:8000/v1/chat/completions",
    "openrouter": "https://openrouter.ai/api/v1/chat/completions",
}
DEFAULT_MODELS: dict[str, str] = {
    # Default Ollama model. Override at runtime by setting MM_AI_LLM_MODEL
    # to whatever model name has been pulled locally (`ollama list`).
    "ollama": "qwen2.5:7b",
    "openai_compatible": "local-model",
    "openrouter": "openai/gpt-4o-mini",
}

# Local-LLM generation can be slow on CPU-only hardware (e.g. ``qwen2.5:7b``
# on a laptop takes ~45-90 s for a multi-symbol Talk to Market prompt). The
# default is sized to give those runs enough headroom while still capping
# pathological hangs. Override with ``MM_AI_LLM_TIMEOUT_SECONDS=<seconds>``.
DEFAULT_TIMEOUT_SECONDS = 120.0
MIN_TIMEOUT_SECONDS = 1.0
MAX_TIMEOUT_SECONDS = 600.0


@dataclass(frozen=True)
class LLMConfig:
    backend_type: str
    model_name: str
    endpoint_url: str
    timeout_seconds: float
    api_key: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "backend_type": self.backend_type,
            "model_name": self.model_name,
            "endpoint_url": self.endpoint_url,
            "timeout_seconds": self.timeout_seconds,
            "api_key_configured": bool(self.api_key),
        }


def _coerce_timeout(raw: str | None) -> float:
    if raw is None or not str(raw).strip():
        return DEFAULT_TIMEOUT_SECONDS
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return DEFAULT_TIMEOUT_SECONDS
    return max(MIN_TIMEOUT_SECONDS, min(MAX_TIMEOUT_SECONDS, value))


def load_config_from_env() -> LLMConfig:
    """Build an :class:`LLMConfig` from environment variables.

    Raises ``ValueError`` only for an explicitly unsupported backend name —
    every other field falls back to a documented default.
    """
    backend_default = "openrouter" if os.environ.get("OPENROUTER_API_KEY") else "ollama"
    backend_raw = (os.environ.get(ENV_BACKEND) or backend_default).strip().lower()
    if backend_raw not in SUPPORTED_BACKENDS:
        raise ValueError(
            f"unsupported backend {backend_raw!r}; "
            f"choose one of {SUPPORTED_BACKENDS}"
        )
    default_endpoint = DEFAULT_ENDPOINTS[backend_raw]
    default_model = DEFAULT_MODELS[backend_raw]
    endpoint = (os.environ.get(ENV_ENDPOINT) or "").strip() or default_endpoint
    if backend_raw == "openrouter":
        model = (
            os.environ.get(ENV_MODEL)
            or os.environ.get("OPENROUTER_MODEL")
            or ""
        ).strip() or default_model
        api_key = (
            os.environ.get("OPENROUTER_API_KEY")
            or os.environ.get("OPENAI_API_KEY")
            or ""
        ).strip()
    else:
        model = (os.environ.get(ENV_MODEL) or "").strip() or default_model
        api_key = ""
    timeout = _coerce_timeout(os.environ.get(ENV_TIMEOUT))
    return LLMConfig(
        backend_type=backend_raw,
        model_name=model,
        endpoint_url=endpoint,
        timeout_seconds=timeout,
        api_key=api_key,
    )
