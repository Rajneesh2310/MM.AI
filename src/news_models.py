"""Plain data containers for MM.AI news headline extracts.

No article body, summary, sentiment, or AI-derived field is included.
These containers carry only what is rendered live from a public RSS feed.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class NewsItem:
    """A single live-fetched headline reference.

    Fields:
        headline:  exact title string as published by the source
        source:    source/site name (may be ``None`` if the feed omits it)
        url:       canonical link to the article (not fetched, not stored)
        timestamp: MM.AI fetch/render time in ``DD:MM:YY HH:MM:SS``
    """

    headline: str
    source: str | None
    url: str
    timestamp: str


@dataclass(frozen=True)
class NewsResult:
    """Deterministic envelope for one fetch_symbol_news invocation."""

    symbol: str
    timestamp: str
    count: int
    items: list[NewsItem] = field(default_factory=list)
    source_query_url: str = ""
    error: str | None = None
