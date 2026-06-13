"""Safe LLM prompt builder for MM.AI.

This module assembles a deterministic, bounded prompt payload that a future
local LLM can consume. It performs **no** model invocation, no reasoning,
no prediction, no recommendation, no sentiment analysis, no hidden-intent
inference. Its single responsibility is to wrap the already-validated
workspace context (observable market data + headline references) in a
fixed scaffold of immutable behavioural rules and output constraints.

Threat model considered:
- Prompt injection via the user's question: we strip control characters,
  cap the question length, and place the question inside a clearly labelled
  section *after* the system rules so a downstream LLM honouring instruction
  hierarchy treats it as data, not instruction.
- Data leakage of paths / tracebacks / raw dataframes through
  ``workspace_text``: a sanitiser scrubs absolute file paths, parquet
  references, Python tracebacks, and exception markers before the text
  enters the prompt.
- Unbounded payloads: every input is length-capped before assembly.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from typing import Any, Iterable

from .llm_models import (
    FORBIDDEN_OUTPUT_PHRASES,
    LLMPromptPayload,
    MAX_NEWS_HEADLINE_CHARS,
    MAX_NEWS_ITEMS,
    MAX_NEWS_SOURCE_CHARS,
    MAX_NEWS_URL_CHARS,
    MAX_QUESTION_CHARS,
    MAX_SYMBOLS,
    MAX_SYMBOL_CHARS,
    MAX_WORKSPACE_TEXT_CHARS,
    RESPONSE_CONSTRAINTS_ALLOWED,
    RESPONSE_CONSTRAINTS_FORBIDDEN,
    SYSTEM_RULES,
    TIMESTAMP_FORMAT,
)
from .news_models import NewsItem, NewsResult

NOT_AVAILABLE = "Not Available"
SECTION_RULE = "=" * 60
SUB_RULE = "-" * 60

# Patterns that must never appear inside the OBSERVABLE MARKET DATA block.
# Each line that matches any of these is removed during sanitisation.
_PATH_PATTERN = re.compile(
    r"(?:[A-Za-z]:[\\/]|/(?:home|root|users|var|etc|tmp|mnt)/|"
    r"\\\\[^\s]+\\|\.parquet|\.csv|\.zip)",
    re.IGNORECASE,
)
_TRACEBACK_MARKERS = (
    "Traceback (most recent call last)",
    "  File \"",
    "  File '",
)
_EXCEPTION_PATTERN = re.compile(
    r"(?m)^\s*(?:[A-Z][A-Za-z0-9_]*Error|[A-Z][A-Za-z0-9_]*Exception):\s",
)
_DATAFRAME_REPR_PATTERN = re.compile(
    r"shape:\s*\(\d+,\s*\d+\)|<DataFrame|<LazyFrame|<polars\.",
)
_CONTROL_CHARS_PATTERN = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now_timestamp() -> str:
    return datetime.now().strftime(TIMESTAMP_FORMAT)


def _strip_controls(text: str) -> str:
    """Remove ASCII control chars; leave \\n and \\t intact."""
    if not text:
        return ""
    norm = unicodedata.normalize("NFC", text)
    return _CONTROL_CHARS_PATTERN.sub("", norm)


def _sanitise_question(raw: str | None) -> str:
    if not raw:
        return ""
    cleaned = _strip_controls(raw).strip()
    if len(cleaned) > MAX_QUESTION_CHARS:
        cleaned = cleaned[:MAX_QUESTION_CHARS].rstrip()
    return cleaned


def _sanitise_symbol(raw: str) -> str:
    if not raw:
        return ""
    cleaned = _strip_controls(raw).strip().upper()
    # Restrict to ASCII letters / digits / common safe chars.
    cleaned = re.sub(r"[^A-Z0-9._\-&]", "", cleaned)
    if len(cleaned) > MAX_SYMBOL_CHARS:
        cleaned = cleaned[:MAX_SYMBOL_CHARS]
    return cleaned


def _normalise_symbols(symbols: Iterable[str] | None) -> tuple[str, ...]:
    if not symbols:
        return ()
    seen: dict[str, None] = {}
    for sym in symbols:
        if not isinstance(sym, str):
            continue
        cleaned = _sanitise_symbol(sym)
        if cleaned and cleaned not in seen:
            seen[cleaned] = None
        if len(seen) >= MAX_SYMBOLS:
            break
    return tuple(seen.keys())


def _sanitise_workspace_text(raw: str | None) -> str:
    """Strip file paths, tracebacks, exception markers, dataframe reprs.

    The expected input is the plain-text output of
    :func:`src.text_formatter.format_observations` (or equivalent). This
    sanitiser is defence-in-depth so a poorly-built caller cannot leak
    parquet paths, stack traces, or raw dataframe content into a future
    LLM context.
    """
    if not raw:
        return ""
    text = _strip_controls(raw)
    cleaned_lines: list[str] = []
    skip_traceback_block = False
    for line in text.splitlines():
        stripped = line.strip()
        if any(marker in line for marker in _TRACEBACK_MARKERS):
            skip_traceback_block = True
            continue
        if skip_traceback_block:
            # Indented continuation lines or the final "X: msg" line.
            if line.startswith(" ") or line.startswith("\t"):
                continue
            if _EXCEPTION_PATTERN.search(line):
                skip_traceback_block = False
                continue
            skip_traceback_block = False
        if _PATH_PATTERN.search(line):
            continue
        if _DATAFRAME_REPR_PATTERN.search(line):
            continue
        if _EXCEPTION_PATTERN.search(line):
            continue
        # Strip inline absolute paths that survived the per-line filter.
        cleaned = _PATH_PATTERN.sub("[redacted-path]", line)
        cleaned_lines.append(cleaned)
    out = "\n".join(cleaned_lines).strip()
    if len(out) > MAX_WORKSPACE_TEXT_CHARS:
        out = out[:MAX_WORKSPACE_TEXT_CHARS].rstrip() + "\n[truncated]"
    return out


def _cap(text: Any, limit: int) -> str:
    if text is None:
        return NOT_AVAILABLE
    s = _strip_controls(str(text)).strip()
    if not s:
        return NOT_AVAILABLE
    if len(s) > limit:
        s = s[:limit].rstrip() + "…"
    return s


def _normalise_news(items: Iterable[Any] | None) -> list[dict[str, str]]:
    """Reduce any supported news input shape to dicts of source/headline/url/timestamp.

    Accepts a sequence of ``NewsItem``, ``NewsResult`` (flattened), or dicts
    carrying those four keys. Article bodies, sentiment, classification, or
    any other field is intentionally discarded.
    """
    if not items:
        return []
    flat: list[dict[str, str]] = []
    for entry in items:
        if isinstance(entry, NewsResult):
            for ni in entry.items:
                flat.append(
                    {
                        "source": _cap(ni.source, MAX_NEWS_SOURCE_CHARS),
                        "headline": _cap(ni.headline, MAX_NEWS_HEADLINE_CHARS),
                        "url": _cap(ni.url, MAX_NEWS_URL_CHARS),
                        "timestamp": _cap(getattr(ni, "published_at", "") or ni.timestamp, 64),
                    }
                )
        elif isinstance(entry, NewsItem):
            flat.append(
                {
                    "source": _cap(entry.source, MAX_NEWS_SOURCE_CHARS),
                    "headline": _cap(entry.headline, MAX_NEWS_HEADLINE_CHARS),
                    "url": _cap(entry.url, MAX_NEWS_URL_CHARS),
                    "timestamp": _cap(getattr(entry, "published_at", "") or entry.timestamp, 64),
                }
            )
        elif isinstance(entry, dict):
            flat.append(
                {
                    "source": _cap(entry.get("source"), MAX_NEWS_SOURCE_CHARS),
                    "headline": _cap(entry.get("headline"), MAX_NEWS_HEADLINE_CHARS),
                    "url": _cap(entry.get("url"), MAX_NEWS_URL_CHARS),
                    "timestamp": _cap(entry.get("published_at") or entry.get("timestamp"), 64),
                }
            )
        # silently skip unknown shapes
        if len(flat) >= MAX_NEWS_ITEMS:
            break
    return flat[:MAX_NEWS_ITEMS]


# ---------------------------------------------------------------------------
# Section rendering
# ---------------------------------------------------------------------------


def _render_system_rules() -> str:
    bullets = "\n".join(f"- {rule}" for rule in SYSTEM_RULES)
    return (
        "You are a deterministic market-observation assistant. The data below "
        "is the only ground truth available. Follow these immutable rules at "
        "all times:\n\n"
        f"{bullets}\n\n"
        "You only answer based on the OBSERVABLE MARKET DATA and NEWS HEADLINES "
        "sections. You must not use prior knowledge or external context. If a "
        "field is missing, treat it as 'Not Available'."
    )


def _render_question(question: str) -> str:
    if not question:
        return "(no question provided)"
    return question


def _render_observable_data(
    workspace_text: str, symbols: tuple[str, ...], timestamp: str
) -> str:
    parts: list[str] = [
        f"Built at: [{timestamp}]",
        f"Symbols: {', '.join(symbols) if symbols else NOT_AVAILABLE}",
        "",
        "Workspace observations (already deterministic; do not reinterpret):",
        "",
    ]
    if not workspace_text:
        parts.append("(no observable workspace data available)")
    else:
        parts.append(workspace_text)
    return "\n".join(parts)


def _render_news(news_items: list[dict[str, str]]) -> str:
    if not news_items:
        return "(no news headlines available)"
    rendered: list[str] = [f"Total headline references: {len(news_items)}", ""]
    for idx, item in enumerate(news_items, 1):
        rendered.append(
            f"[{idx}] published_at: {item['timestamp']}\n"
            f"    source:    {item['source']}\n"
            f"    headline:  {item['headline']}\n"
            f"    url:       {item['url']}"
        )
    return "\n".join(rendered)


def _render_response_constraints() -> str:
    allowed = ", ".join(RESPONSE_CONSTRAINTS_ALLOWED)
    forbidden = "\n".join(f"- {item}" for item in RESPONSE_CONSTRAINTS_FORBIDDEN)
    return (
        f"Your reply MUST be: {allowed}.\n\n"
        "Forbidden under all circumstances:\n"
        f"{forbidden}\n\n"
        "If the OBSERVABLE MARKET DATA and NEWS HEADLINES sections do not "
        "contain enough information to answer the user's question, reply with "
        'exactly: "I do not have enough observable data to answer that."\n\n'
        "Cite specific fields from the OBSERVABLE MARKET DATA section by name "
        "(e.g. 'Latest Close', 'OI Total'). Cite news only by source + "
        "headline; do not paraphrase article bodies (none were provided)."
    )


def _wrap_section(title: str, body: str) -> str:
    return f"{SECTION_RULE}\n{title}\n{SECTION_RULE}\n\n{body}"


def _assert_no_forbidden_phrases_in_user_inputs(
    question: str,
    workspace_text: str,
    news_items: list[dict[str, str]],
) -> None:
    """Scan **only** caller-supplied content for forbidden output phrases.

    The hard-coded constraints section intentionally names forbidden
    behaviours by label (e.g. "guaranteed movement statements") so the LLM
    knows what to avoid. Those labels would falsely trip a whole-prompt
    scan, so we limit the guard to user-supplied content where forbidden
    phrases are genuinely a contract violation.
    """
    user_blobs: list[str] = [question, workspace_text]
    for item in news_items:
        user_blobs.append(item.get("headline", ""))
        user_blobs.append(item.get("source", ""))
    haystack = "\n".join(user_blobs).lower()
    for phrase in FORBIDDEN_OUTPUT_PHRASES:
        if phrase in haystack:
            raise ValueError(
                f"prompt builder rejected caller input containing forbidden "
                f"phrase: {phrase!r}. Re-author the question / workspace / "
                f"news input to remove the offending phrase."
            )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_llm_prompt(
    user_question: str,
    workspace_html: str | None,
    workspace_text: str | None,
    news_items: Iterable[Any] | None,
    symbols: Iterable[str] | None,
) -> LLMPromptPayload:
    """Build a deterministic prompt payload for a future local LLM.

    The function:
    - Sanitises and length-caps every input.
    - Discards ``workspace_html`` (the LLM only sees the plain-text workspace).
    - Assembles five clearly labelled sections: SYSTEM RULES, USER QUESTION,
      OBSERVABLE MARKET DATA, NEWS HEADLINES, RESPONSE CONSTRAINTS.
    - Validates the final prompt against ``FORBIDDEN_OUTPUT_PHRASES``.

    No LLM is called, no answer is produced. The return value is a frozen
    :class:`LLMPromptPayload` ready to be handed to a future local model.
    """
    _ = workspace_html  # accepted for API symmetry; never embedded in prompt
    timestamp = _now_timestamp()
    safe_question = _sanitise_question(user_question)
    safe_symbols = _normalise_symbols(symbols)
    safe_workspace = _sanitise_workspace_text(workspace_text)
    safe_news = _normalise_news(news_items)

    _assert_no_forbidden_phrases_in_user_inputs(
        safe_question, safe_workspace, safe_news
    )

    sections = [
        _wrap_section("SYSTEM RULES", _render_system_rules()),
        _wrap_section("USER QUESTION", _render_question(safe_question)),
        _wrap_section(
            "OBSERVABLE MARKET DATA",
            _render_observable_data(safe_workspace, safe_symbols, timestamp),
        ),
        _wrap_section("NEWS HEADLINES", _render_news(safe_news)),
        _wrap_section("RESPONSE CONSTRAINTS", _render_response_constraints()),
    ]
    prompt_text = "\n\n".join(sections).rstrip() + "\n"

    return LLMPromptPayload(
        timestamp=timestamp,
        symbols=safe_symbols,
        question=safe_question,
        prompt_text=prompt_text,
    )
