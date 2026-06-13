"""Lightweight live news headline fetcher for MM.AI.

Fetches public RSS headlines for a symbol and returns deterministic
``NewsItem`` records (headline / source / url / render timestamp). The fetcher
performs exactly one HTTP request per call, parses the response as XML using
the stdlib, and returns the first ``limit`` items.

Nothing is cached, persisted, summarised, classified, or interpreted. Article
bodies are never fetched. Sentiment, causation, recommendations, and AI
narrative are explicitly out of scope.

CLI::

    python -m src.news_fetcher RELIANCE
    python -m src.news_fetcher RELIANCE --limit 5 --timeout 10
"""

from __future__ import annotations

import argparse
import socket
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree as ET

from .news_models import NewsItem, NewsResult

TIMESTAMP_FORMAT = "%d:%m:%y %H:%M:%S"
DEFAULT_TIMEOUT_SECONDS = 10.0
USER_AGENT = "MM.AI/0.1 (read-only headline fetcher; +https://example.invalid)"
GOOGLE_NEWS_RSS = (
    "https://news.google.com/rss/search?q={query}&hl=en-IN&gl=IN&ceid=IN:en"
)


def _now_timestamp() -> str:
    return datetime.now().strftime(TIMESTAMP_FORMAT)


def _query_url(symbol: str) -> str:
    return GOOGLE_NEWS_RSS.format(query=urllib.parse.quote_plus(symbol))


def _fetch_bytes(url: str, timeout: float) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def _parse_items(body: bytes, limit: int, timestamp: str) -> list[NewsItem]:
    root = ET.fromstring(body)
    channel = root.find("channel")
    if channel is None:
        return []
    items: list[NewsItem] = []
    for item_el in channel.findall("item"):
        if len(items) >= limit:
            break
        title = (item_el.findtext("title") or "").strip()
        link = (item_el.findtext("link") or "").strip()
        published_at = _normalise_pubdate(item_el.findtext("pubDate"))
        if not title or not link:
            continue
        source_el = item_el.find("source")
        source = source_el.text.strip() if source_el is not None and source_el.text else None
        items.append(
            NewsItem(
                headline=title,
                source=source,
                url=link,
                timestamp=timestamp,
                published_at=published_at,
            )
        )
    items.sort(key=lambda item: item.published_at or "", reverse=True)
    return items


def _normalise_pubdate(raw: str | None) -> str:
    if not raw:
        return ""
    try:
        parsed = parsedate_to_datetime(raw.strip())
    except (TypeError, ValueError, IndexError, OverflowError):
        return raw.strip()
    return parsed.isoformat()


def fetch_symbol_news(
    symbol: str,
    limit: int = 5,
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> NewsResult:
    """Fetch live public headlines for ``symbol``.

    Parameters
    ----------
    symbol:
        Ticker or index name (e.g. ``RELIANCE``, ``INFY``, ``NIFTY``).
    limit:
        Maximum number of headlines to return. Clamped to ``>= 1``.
    timeout:
        Per-request HTTP timeout in seconds.

    Returns
    -------
    NewsResult
        Deterministic envelope. On failure, ``items`` is empty and ``error``
        is a short factual token (``blank_symbol``, ``timeout``,
        ``fetch_failed``, ``malformed_xml``, ``no_channel``,
        ``no_headlines``, or ``unexpected:<ExcType>``).
    """
    sym = (symbol or "").strip().upper()
    timestamp = _now_timestamp()
    if not sym:
        return NewsResult(symbol="", timestamp=timestamp, count=0, error="blank_symbol")

    capped_limit = max(1, int(limit))
    url = _query_url(sym)

    try:
        body = _fetch_bytes(url, timeout=timeout)
    except socket.timeout:
        return NewsResult(symbol=sym, timestamp=timestamp, count=0, source_query_url=url, error="timeout")
    except urllib.error.HTTPError as exc:
        return NewsResult(
            symbol=sym,
            timestamp=timestamp,
            count=0,
            source_query_url=url,
            error=f"http_{exc.code}",
        )
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        return NewsResult(
            symbol=sym,
            timestamp=timestamp,
            count=0,
            source_query_url=url,
            error=f"fetch_failed: {reason}",
        )
    except Exception as exc:  # noqa: BLE001 — factual fallback
        return NewsResult(
            symbol=sym,
            timestamp=timestamp,
            count=0,
            source_query_url=url,
            error=f"unexpected: {type(exc).__name__}",
        )

    try:
        items = _parse_items(body, capped_limit, timestamp)
    except ET.ParseError as exc:
        return NewsResult(
            symbol=sym,
            timestamp=timestamp,
            count=0,
            source_query_url=url,
            error=f"malformed_xml: {exc}",
        )

    if not items:
        return NewsResult(
            symbol=sym,
            timestamp=timestamp,
            count=0,
            source_query_url=url,
            error="no_headlines",
        )

    return NewsResult(
        symbol=sym,
        timestamp=timestamp,
        count=len(items),
        items=items,
        source_query_url=url,
        error=None,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _print_result(result: NewsResult) -> None:
    print(f"[{result.timestamp}]")
    print()
    print(f"SYMBOL: {result.symbol or 'Not Available'}")
    print(f"QUERY URL: {result.source_query_url or 'Not Available'}")
    print(f"COUNT: {result.count}")
    if result.error:
        print(f"ERROR: {result.error}")
    print()
    for idx, item in enumerate(result.items, start=1):
        print(f"#{idx}")
        print(f"  HEADLINE: {item.headline}")
        print(f"  SOURCE: {item.source or 'Not Available'}")
        print(f"  URL: {item.url}")
        print()


def _reconfigure_stdout_utf8() -> None:
    """Headlines may carry non-ASCII characters (e.g. ₹). Force UTF-8 stdout."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass


def main(argv: list[str] | None = None) -> int:
    _reconfigure_stdout_utf8()
    parser = argparse.ArgumentParser(
        prog="news_fetcher",
        description="MM.AI live headline fetcher — read-only, public RSS only.",
    )
    parser.add_argument("symbol", help="Symbol or index name, e.g. RELIANCE")
    parser.add_argument(
        "--limit",
        type=int,
        default=5,
        help="Maximum headlines to print (default: 5).",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT_SECONDS,
        help=f"HTTP timeout in seconds (default: {DEFAULT_TIMEOUT_SECONDS}).",
    )
    args = parser.parse_args(argv)

    if args.limit < 1:
        print("error: --limit must be >= 1", file=sys.stderr)
        return 2
    if args.timeout <= 0:
        print("error: --timeout must be > 0", file=sys.stderr)
        return 2

    result = fetch_symbol_news(args.symbol, limit=args.limit, timeout=args.timeout)
    _print_result(result)
    if result.error:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
