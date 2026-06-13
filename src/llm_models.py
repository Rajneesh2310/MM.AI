"""Immutable data containers for the MM.AI LLM prompt-builder layer.

This module deliberately holds **no behaviour** — only constants and frozen
dataclasses. The prompt-builder consumes these to assemble a deterministic
prompt payload that a *future* local LLM can read.

Nothing in this module calls an LLM, performs reasoning, predicts, or makes
recommendations. The constants here are the immutable behavioural contract
the LLM will be asked to follow.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# ---------------------------------------------------------------------------
# Immutable rule set (verbatim — order is part of the contract).
# ---------------------------------------------------------------------------

SYSTEM_RULES: tuple[str, ...] = (
    "Use observable data only.",
    "Do not predict future movement.",
    "Do not recommend trades.",
    "Do not infer institutional intent.",
    "Do not invent causation from news.",
    "If data unavailable, explicitly say so.",
    "Use factual language only.",
    "Never claim certainty beyond provided data.",
    "Do not hallucinate unavailable values.",
)

RESPONSE_CONSTRAINTS_ALLOWED: tuple[str, ...] = (
    "concise",
    "factual",
    "explainable",
    "observable-data-based",
)

RESPONSE_CONSTRAINTS_FORBIDDEN: tuple[str, ...] = (
    "bullish/bearish certainty",
    "hidden smart-money claims",
    "accumulation/distribution claims",
    "guaranteed movement statements",
    "financial advice",
)

# Phrases the assembled prompt must never contain. The builder asserts these
# are absent after sanitisation; tests guard the contract.
FORBIDDEN_OUTPUT_PHRASES: tuple[str, ...] = (
    "guaranteed",
    "smart money",
    "accumulation",
    "distribution",
    "buy signal",
    "sell signal",
    "target price",
    "stop loss",
    "should buy",
    "should sell",
    "will rally",
    "will crash",
    "is bullish",
    "is bearish",
)

# Hard input limits — prevent prompt injection via huge payloads.
MAX_QUESTION_CHARS = 512
MAX_WORKSPACE_TEXT_CHARS = 16_000
MAX_NEWS_ITEMS = 50
MAX_NEWS_HEADLINE_CHARS = 400
MAX_NEWS_URL_CHARS = 1_024
MAX_NEWS_SOURCE_CHARS = 200
MAX_SYMBOLS = 20
MAX_SYMBOL_CHARS = 40

# Timestamp format used everywhere in MM.AI.
TIMESTAMP_FORMAT = "%d:%m:%y %H:%M:%S"


@dataclass(frozen=True)
class LLMPromptPayload:
    """The deterministic package handed to a future local LLM.

    Attributes:
        timestamp:    Build time in ``DD:MM:YY HH:MM:SS``.
        symbols:      Sanitised, uppercase symbol list (deduplicated, ordered).
        question:     Sanitised user question (control chars stripped, length-capped).
        prompt_text:  Fully assembled prompt string the LLM should consume verbatim.
    """

    timestamp: str
    symbols: tuple[str, ...]
    question: str
    prompt_text: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "symbols": list(self.symbols),
            "question": self.question,
            "prompt_text": self.prompt_text,
        }
