"""Immutable container for the local-LLM adapter response.

Owns no behaviour — only the shape of what ``generate_llm_response`` returns.
The adapter never raises on failure; all failure modes are surfaced through
this dataclass via ``ok=False`` and a deterministic ``error`` string.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class LLMResponse:
    """Outcome of a single local-LLM call.

    Attributes:
        ok:            True iff the model returned plain text successfully.
        backend:       ``"ollama"`` or ``"openai_compatible"`` (best-effort
                       on config errors — may be empty string).
        model:         Model name the adapter sent in the request.
        endpoint:      URL the adapter posted to (always a local address).
        timestamp:     Build time in ``DD:MM:YY HH:MM:SS``.
        response_text: Verbatim model response. Empty string on failure.
        error:         ``None`` on success; deterministic short token on
                       failure (e.g. ``"timeout"``,
                       ``"connection_failure: ..."``,
                       ``"malformed_response: ..."``).
        elapsed_ms:    Wall-clock duration of the call attempt.
        prompt_chars:  Length of the prompt text actually sent.
    """

    ok: bool
    backend: str
    model: str
    endpoint: str
    timestamp: str
    response_text: str
    error: str | None
    elapsed_ms: int
    prompt_chars: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "backend": self.backend,
            "model": self.model,
            "endpoint": self.endpoint,
            "timestamp": self.timestamp,
            "response_text": self.response_text,
            "error": self.error,
            "elapsed_ms": self.elapsed_ms,
            "prompt_chars": self.prompt_chars,
        }
