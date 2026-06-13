"""Tests for the live news headline fetcher.

Network is mocked — these tests never hit the real internet.
"""

from __future__ import annotations

import io
import re
import socket
import sys
import urllib.error
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.news_fetcher import TIMESTAMP_FORMAT, fetch_symbol_news  # noqa: E402
from src.news_models import NewsItem, NewsResult  # noqa: E402

TS_RE = re.compile(r"^\d{2}:\d{2}:\d{2} \d{2}:\d{2}:\d{2}$")


def _rss(items_xml: str) -> bytes:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0"><channel>'
        "<title>MM.AI fixture</title>"
        f"{items_xml}"
        "</channel></rss>"
    ).encode("utf-8")


def _item(
    title: str,
    link: str,
    source: str | None = None,
    source_url: str = "https://example.invalid",
    pub_date: str | None = None,
) -> str:
    src = f'<source url="{source_url}">{source}</source>' if source else ""
    pub = f"<pubDate>{pub_date}</pubDate>" if pub_date else ""
    return f"<item><title>{title}</title><link>{link}</link>{src}{pub}</item>"


class _FakeResponse:
    def __init__(self, payload: bytes):
        self._buf = io.BytesIO(payload)

    def read(self) -> bytes:
        return self._buf.read()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self._buf.close()
        return False


def _patch_urlopen(payload: bytes):
    return patch(
        "src.news_fetcher.urllib.request.urlopen",
        return_value=_FakeResponse(payload),
    )


def _patch_urlopen_raises(exc: BaseException):
    def _raise(*_args, **_kwargs):
        raise exc

    return patch("src.news_fetcher.urllib.request.urlopen", side_effect=_raise)


def test_returns_news_items_for_populated_feed():
    xml = "".join(
        [
            _item("Reliance Q4 results released", "https://news.example/reliance-q4", "ExampleWire"),
            _item("Reliance Jio update", "https://news.example/jio", "MarketDesk"),
            _item("Reliance retail expansion", "https://news.example/retail", "Wire24"),
        ]
    )
    with _patch_urlopen(_rss(xml)):
        result = fetch_symbol_news("reliance", limit=5)

    assert isinstance(result, NewsResult)
    assert result.symbol == "RELIANCE"
    assert TS_RE.match(result.timestamp)
    assert result.count == 3
    assert result.error is None
    assert result.source_query_url.startswith("https://news.google.com/rss/search?q=RELIANCE")
    assert all(isinstance(item, NewsItem) for item in result.items)
    assert result.items[0].headline == "Reliance Q4 results released"
    assert result.items[0].url == "https://news.example/reliance-q4"
    assert result.items[0].source == "ExampleWire"
    assert result.items[0].timestamp == result.timestamp


def test_respects_limit():
    xml = "".join(_item(f"Headline {i}", f"https://news.example/{i}", "Wire") for i in range(10))
    with _patch_urlopen(_rss(xml)):
        result = fetch_symbol_news("INFY", limit=3)
    assert result.count == 3
    assert len(result.items) == 3


def test_sorts_items_by_published_date_latest_first():
    xml = "".join(
        [
            _item(
                "Older",
                "https://news.example/older",
                "Wire",
                pub_date="Fri, 12 Jun 2026 09:00:00 GMT",
            ),
            _item(
                "Latest",
                "https://news.example/latest",
                "Wire",
                pub_date="Sat, 13 Jun 2026 10:00:00 GMT",
            ),
        ]
    )
    with _patch_urlopen(_rss(xml)):
        result = fetch_symbol_news("RELIANCE", limit=5)
    assert [item.headline for item in result.items] == ["Latest", "Older"]
    assert result.items[0].published_at.startswith("2026-06-13T10:00:00")


def test_no_items_returns_no_headlines_error():
    with _patch_urlopen(_rss("")):
        result = fetch_symbol_news("NIFTY", limit=5)
    assert result.count == 0
    assert result.items == []
    assert result.error == "no_headlines"


def test_blank_symbol_returns_blank_symbol_error():
    result = fetch_symbol_news("   ", limit=5)
    assert result.symbol == ""
    assert result.count == 0
    assert result.error == "blank_symbol"
    assert result.source_query_url == ""


def test_timeout_returns_timeout_error():
    with _patch_urlopen_raises(socket.timeout("timed out")):
        result = fetch_symbol_news("RELIANCE", limit=5, timeout=1.0)
    assert result.error == "timeout"
    assert result.count == 0
    assert result.source_query_url != ""


def test_http_error_returns_http_token():
    err = urllib.error.HTTPError(
        url="https://news.google.com",
        code=503,
        msg="Service Unavailable",
        hdrs=None,
        fp=None,
    )
    with _patch_urlopen_raises(err):
        result = fetch_symbol_news("RELIANCE", limit=5)
    assert result.error == "http_503"
    assert result.count == 0


def test_url_error_returns_fetch_failed_token():
    err = urllib.error.URLError("Name or service not known")
    with _patch_urlopen_raises(err):
        result = fetch_symbol_news("RELIANCE", limit=5)
    assert result.error is not None
    assert result.error.startswith("fetch_failed")


def test_malformed_xml_returns_parse_error():
    with _patch_urlopen(b"<not-xml<"):
        result = fetch_symbol_news("RELIANCE", limit=5)
    assert result.error is not None
    assert result.error.startswith("malformed_xml")
    assert result.count == 0


def test_timestamp_format_matches_spec():
    xml = _item("X", "https://news.example/x")
    with _patch_urlopen(_rss(xml)):
        result = fetch_symbol_news("RELIANCE", limit=1)
    assert TIMESTAMP_FORMAT == "%d:%m:%y %H:%M:%S"
    assert TS_RE.match(result.timestamp)
    assert result.items[0].timestamp == result.timestamp


def test_limit_clamped_to_one():
    xml = _item("Only one", "https://news.example/one")
    with _patch_urlopen(_rss(xml)):
        result = fetch_symbol_news("RELIANCE", limit=0)
    assert result.count == 1


def test_query_url_uses_uppercased_symbol():
    xml = _item("X", "https://news.example/x")
    with _patch_urlopen(_rss(xml)):
        result = fetch_symbol_news("  reliance  ", limit=1)
    assert "q=RELIANCE" in result.source_query_url


def test_item_missing_source_returns_none_source():
    xml = _item("No source", "https://news.example/no-source")
    with _patch_urlopen(_rss(xml)):
        result = fetch_symbol_news("RELIANCE", limit=1)
    assert result.items[0].source is None
