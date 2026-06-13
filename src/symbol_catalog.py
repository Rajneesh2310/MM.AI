"""Read-only adapter to the symbol catalog that MM already maintains.

MM owns the canonical symbol universe. It writes two JSON cache files into
``<MM_INSTALL_ROOT>/data/`` whenever it refreshes the universe:

    cash_symbols.json   -> ["20MICRONS", "21STCENMGM", "360ONE", ...]   (~2 600 entries)
    fo_symbols.json     -> ["360ONE", "ABB", "ABCAPITAL", ...,
                            "NIFTY", "BANKNIFTY", ...]                  (~ 220 entries)

This module **consumes** those files. It never writes them, never imports
``mm_backend``, and never modifies anything inside the MM tree. If the JSON
caches are missing on a given install, it falls back to enumerating
``data/cash/SYMBOL=*`` and ``data/fo/SYMBOL=*`` directories (also read-only).

Public surface:

- :func:`list_cash_symbols`
- :func:`list_fo_symbols`
- :func:`list_all_symbols`
- :func:`find_matches`  -- deterministic fuzzy ranking for partial input

No persistence is added. The in-memory cache lives for the lifetime of the
process and can be cleared via :func:`clear_cache` (used by tests).
"""

from __future__ import annotations

import difflib
import json
import re
import threading
from pathlib import Path

from . import config

# JSON cache file names (these are MM's own artifacts — DO NOT rename).
_CASH_CACHE = "cash_symbols.json"
_FO_CACHE = "fo_symbols.json"

# Parquet partition directory names (fallback when JSON cache is missing).
_CASH_DIR = "cash"
_FO_DIR = "fo"
_PARTITION_PREFIX = "SYMBOL="

DEFAULT_MATCH_LIMIT = 8
_SIMILARITY_CUTOFF = 0.45

# Symbol-character whitelist for query sanitisation. NSE symbols use
# ``A-Z 0-9 . - & _``.
_SYMBOL_CHAR_RE = re.compile(r"[^A-Z0-9.\-&_]")

_lock = threading.Lock()
_cache: dict[str, tuple[str, ...]] = {}


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def _load_from_json(path: Path) -> list[str]:
    if not path.is_file():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(raw, list):
        return []
    return [str(s).strip().upper() for s in raw if isinstance(s, str) and s.strip()]


def _load_from_partitions(root: Path) -> list[str]:
    if not root.is_dir():
        return []
    seen: list[str] = []
    try:
        for entry in root.iterdir():
            if not entry.is_dir():
                continue
            name = entry.name
            if not name.startswith(_PARTITION_PREFIX):
                continue
            sym = name[len(_PARTITION_PREFIX):].strip().upper()
            if sym:
                seen.append(sym)
    except OSError:
        return []
    return seen


def _segment_symbols(segment: str) -> tuple[str, ...]:
    if segment == "cash":
        cache_path = config.data_root() / _CASH_CACHE
        partition_root = config.cash_root()
    elif segment == "fo":
        cache_path = config.data_root() / _FO_CACHE
        partition_root = config.fo_root()
    else:
        raise ValueError(f"unknown segment: {segment!r}")
    symbols = _load_from_json(cache_path)
    if not symbols:
        symbols = _load_from_partitions(partition_root)
    deduped: dict[str, None] = {}
    for s in symbols:
        if s and s not in deduped:
            deduped[s] = None
    return tuple(sorted(deduped))


def _cached(segment: str) -> tuple[str, ...]:
    with _lock:
        if segment not in _cache:
            _cache[segment] = _segment_symbols(segment)
        return _cache[segment]


def clear_cache() -> None:
    """Drop the in-memory cache. Used by tests; safe to call any time."""
    with _lock:
        _cache.clear()


# ---------------------------------------------------------------------------
# Public lookup
# ---------------------------------------------------------------------------


def list_cash_symbols() -> tuple[str, ...]:
    return _cached("cash")


def list_fo_symbols() -> tuple[str, ...]:
    return _cached("fo")


def list_all_symbols() -> tuple[str, ...]:
    """Sorted union of cash + F&O symbols. Empty tuple if neither source exists."""
    union: dict[str, None] = {}
    for s in list_cash_symbols():
        union[s] = None
    for s in list_fo_symbols():
        union[s] = None
    return tuple(sorted(union))


def normalise_query(raw: str | None) -> str:
    """Upper-case, strip whitespace, drop characters not in NSE symbol set."""
    if not raw:
        return ""
    return _SYMBOL_CHAR_RE.sub("", raw.strip().upper())


def is_known(symbol: str | None) -> bool:
    """Return True iff ``symbol`` (case-insensitive, trimmed) is in the union."""
    if not symbol:
        return False
    return symbol.strip().upper() in set(list_all_symbols())


def find_matches(
    query: str | None,
    *,
    limit: int = DEFAULT_MATCH_LIMIT,
    pool: tuple[str, ...] | list[str] | None = None,
) -> list[str]:
    """Return up to ``limit`` likely-match candidates for ``query``.

    Ranking is deterministic (no scoring randomness, no ML):

    1. Exact match.
    2. Symbols whose name starts with the query.
    3. Symbols that contain the query as a substring.
    4. ``difflib.get_close_matches`` similarity (cutoff = 0.45) for the
       remainder.

    Duplicates are removed; the relative order of items inside each rank
    bucket follows the lexical order of the catalogue.

    ``pool`` is injected by tests. Production callers omit it so the
    function works against the live catalogue.
    """
    if limit <= 0:
        return []
    q = normalise_query(query)
    if not q:
        return []
    candidates = tuple(pool) if pool is not None else list_all_symbols()
    if not candidates:
        return []

    exact: list[str] = []
    prefix: list[str] = []
    contains: list[str] = []
    for sym in candidates:
        if sym == q:
            exact.append(sym)
        elif sym.startswith(q):
            prefix.append(sym)
        elif q in sym:
            contains.append(sym)

    ordered: list[str] = []
    seen: set[str] = set()
    for bucket in (exact, prefix, contains):
        for sym in bucket:
            if sym in seen:
                continue
            seen.add(sym)
            ordered.append(sym)
            if len(ordered) >= limit:
                return ordered

    if len(ordered) < limit:
        remaining_pool = [s for s in candidates if s not in seen]
        fuzzy = difflib.get_close_matches(
            q,
            remaining_pool,
            n=limit - len(ordered),
            cutoff=_SIMILARITY_CUTOFF,
        )
        for sym in fuzzy:
            if sym not in seen:
                seen.add(sym)
                ordered.append(sym)

    return ordered[:limit]
