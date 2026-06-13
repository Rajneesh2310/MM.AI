"""Plain data containers for MM.AI symbol extracts.

These dataclasses carry observable parquet rows only. They contain no logic,
no comparisons, and no derived metrics.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class CashData:
    """Cash parquet rows for one symbol."""

    symbol: str
    latest_session: str | None = None
    latest_row: dict[str, Any] | None = None
    previous_sessions: list[str] = field(default_factory=list)
    previous_rows: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class FoData:
    """F&O parquet rows for one symbol."""

    symbol: str
    latest_session: str | None = None
    latest_session_rows: list[dict[str, Any]] = field(default_factory=list)
    previous_sessions: list[str] = field(default_factory=list)
    previous_session_rows: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class SymbolData:
    """Combined per-symbol extract from MM cash and F&O parquet."""

    symbol: str
    lookback_sessions: int
    cash: CashData
    fo: FoData
