"""Deterministic symbol extractor for Talk to Market questions.

Given a free-text question like::

    "compare nifty and reliance"
    "what changed in RELIANCE today?"

return the ticker symbols mentioned, in order of first appearance, with
duplicates removed::

    ["NIFTY", "RELIANCE"]
    ["RELIANCE"]

There is **no** AI / ML / probabilistic inference here. The extractor is a
pure deterministic function. It performs:

1. Upper-case + punctuation strip on the input.
2. Token split on whitespace / comma / semicolon.
3. Stop-word filter (common English words that would never be tickers).
4. Membership check against either ``known_symbols`` (MM's existing
   catalogue, when supplied) or a small hard-coded **safe-fallback** set
   ``{NIFTY, BANKNIFTY, RELIANCE, INFY}``.

Symbols outside the known catalogue / safe-fallback set are never
invented — the function returns ``[]`` rather than guessing.
"""

from __future__ import annotations

import re
from typing import Iterable

# When the MM catalogue is unavailable the extractor still works for the
# universally-supported MM.AI corpus + common index symbols required by the
# spec. Do NOT invent symbols here — only widely-known tickers.
SAFE_FALLBACK_SYMBOLS: frozenset[str] = frozenset(
    {"NIFTY", "BANKNIFTY", "RELIANCE", "INFY"}
)

# Common English words that must never be classified as a ticker even if a
# rare catalogue entry happens to spell the same letters. Keep this list
# tight — it is purely a false-positive guard, not a grammar tutor.
_STOPWORDS: frozenset[str] = frozenset(
    {
        "A", "AN", "THE",
        "AND", "OR", "BUT", "IF", "NOR", "SO", "YET",
        "OF", "IN", "ON", "AT", "TO", "FROM", "BY", "FOR", "WITH", "INTO",
        "OUT", "OFF", "OVER", "UNDER", "AFTER", "BEFORE", "DURING",
        "WHAT", "WHO", "WHOM", "WHERE", "WHEN", "WHY", "HOW",
        "IS", "ARE", "WAS", "WERE", "BE", "BEEN", "BEING",
        "HAS", "HAVE", "HAD",
        "DO", "DOES", "DID", "DOING", "DONE",
        "WILL", "WOULD", "SHOULD", "COULD", "MIGHT", "MUST", "MAY",
        "CAN", "SHALL", "AM",
        "I", "ME", "MY", "MYSELF",
        "YOU", "YOUR", "YOURS", "YOURSELF",
        "HE", "HIM", "HIS", "HIMSELF",
        "SHE", "HER", "HERS", "HERSELF",
        "IT", "ITS", "ITSELF",
        "WE", "US", "OUR", "OURS",
        "THEY", "THEM", "THEIR", "THEIRS",
        "THIS", "THAT", "THESE", "THOSE",
        "TODAY", "TODAYS", "YESTERDAY", "TOMORROW",
        "NOW", "LATER", "RECENTLY", "RECENT", "CURRENT", "CURRENTLY",
        "WEEK", "MONTH", "YEAR", "DAY", "DAYS", "HOUR", "MIN", "SEC",
        "SHOW", "SHOWS", "SHOWED", "SHOWN", "SHOWING",
        "TELL", "TELLS", "TOLD",
        "GIVE", "GIVES", "GAVE", "GIVEN",
        "GET", "GETS", "GOT",
        "GO", "GOES", "GOING", "WENT",
        "COME", "COMES", "CAME", "COMING",
        "MAKE", "MAKES", "MADE",
        "TAKE", "TAKES", "TOOK", "TAKEN",
        "FIND", "FINDS", "FOUND",
        "USE", "USES", "USED",
        "TRY", "TRIES", "TRIED",
        "ASK", "ASKS", "ASKED",
        "NEED", "NEEDS", "NEEDED",
        "LIKE", "LIKED",
        "WANT", "WANTS", "WANTED",
        "LET",
        "TALK", "TALKS", "TALKED",
        "MARKET", "MARKETS",
        "PRICE", "PRICES", "PRICED",
        "CHANGE", "CHANGES", "CHANGED", "CHANGING",
        "ACTIVITY", "ACTIVITIES",
        "NEWS",
        "COMPARE", "COMPARING", "COMPARED", "COMPARISON", "VERSUS", "VS",
        "ABOUT", "REGARDING",
        "MUCH", "MANY", "FEW", "SOME", "ANY", "ALL", "NONE", "EACH", "EVERY",
        "MORE", "LESS", "MOST", "LEAST",
        "PLEASE", "JUST", "ALSO", "TOO", "VERY", "REALLY",
        "WHICH", "WHOSE", "EITHER", "NEITHER", "BOTH",
        "HERE", "THERE", "EVERYWHERE", "ANYWHERE", "NOWHERE",
        "YES", "NO", "NOT", "DONT", "WONT", "CANT", "ISNT", "ARENT",
        "OK", "OKAY",
        "PERCENT", "PERCENTAGE",
        "VALUE", "VALUES",
        "OPEN", "CLOSE", "HIGH", "LOW", "VOLUME",
    }
)

# Punctuation we treat as token separators (replaced with whitespace
# before splitting). Anything outside [A-Z0-9&] + separators is dropped so
# trailing dots / hyphens / question marks fall away cleanly (e.g.
# "INFY." -> "INFY", "RELIANCE!!!" -> "RELIANCE"). ``&`` is preserved
# because it occurs in real Indian tickers such as ``M&M`` and ``L&T``.
_SEPARATOR_RE = re.compile(r"[,;:\s]+")
_NOISE_RE = re.compile(r"[^A-Z0-9&,;:\s]")


def _tokenise(question: str) -> list[str]:
    """Upper-case the input and split it into ticker-shaped tokens."""
    if not question:
        return []
    upper = question.upper()
    no_noise = _NOISE_RE.sub(" ", upper)
    parts = _SEPARATOR_RE.split(no_noise)
    return [p.strip() for p in parts if p and p.strip()]


def extract_symbols_from_question(
    question: str | None,
    known_symbols: Iterable[str] | None = None,
) -> list[str]:
    """Return the ticker symbols mentioned in ``question``.

    Args:
        question: Free-text user input. ``None`` / empty -> ``[]``.
        known_symbols: When supplied, a token only counts as a symbol if it
            is also a member of this iterable. Pass MM's existing catalogue
            (e.g. ``symbol_catalog.list_all_symbols()``) to keep the
            extractor restricted to real tickers. When omitted, the
            extractor falls back to :data:`SAFE_FALLBACK_SYMBOLS`.

    Returns:
        Upper-cased symbol list, deduplicated, in order of first
        appearance. Empty list when no symbols are mentioned.
    """
    if not question:
        return []

    if known_symbols is None:
        allowed = set(SAFE_FALLBACK_SYMBOLS)
    else:
        allowed = {
            str(s).strip().upper()
            for s in known_symbols
            if s and isinstance(s, str)
        }
        if not allowed:
            allowed = set(SAFE_FALLBACK_SYMBOLS)

    tokens = _tokenise(question)
    seen: dict[str, None] = {}
    for tok in tokens:
        if not tok or tok in _STOPWORDS:
            continue
        if tok in allowed and tok not in seen:
            seen[tok] = None
    return list(seen.keys())


def detect_symbols(
    question: str | None,
    known_symbols: Iterable[str] | None = None,
) -> list[str]:
    """Backwards-friendly alias for :func:`extract_symbols_from_question`."""
    return extract_symbols_from_question(question, known_symbols)
