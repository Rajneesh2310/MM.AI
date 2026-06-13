"""MM.AI unified factual workspace CLI.

Combines two strictly separate sections for one symbol:

1. Deterministic observation block (from
   ``load_symbol_data`` → ``build_observations`` → ``format_observations``).
2. Live news headline block (from ``fetch_symbol_news``).

No section is merged, summarised, classified, or annotated. No sentiment,
causation, recommendation, prediction, or AI narrative is produced.

Usage::

    python -m src.workspace RELIANCE
    python -m src.workspace RELIANCE --lookback 5 --news-limit 5
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime

from .news_fetcher import (
    DEFAULT_TIMEOUT_SECONDS,
    TIMESTAMP_FORMAT,
    _reconfigure_stdout_utf8,
    fetch_symbol_news,
)
from .news_models import NewsResult
from .observation_builder import build_observations
from .symbol_reader import load_symbol_data
from .text_formatter import NA, format_observations

SECTION_RULE = "-" * 50


def _now_timestamp() -> str:
    return datetime.now().strftime(TIMESTAMP_FORMAT)


def _build_observation_section(symbol: str, lookback: int) -> tuple[str, str | None]:
    """Return formatted observation text plus an optional factual error token."""
    try:
        data = load_symbol_data(symbol, lookback_sessions=lookback)
    except ValueError as exc:
        return _stub_observation(symbol), f"observation_input_error: {exc}"
    except OSError as exc:
        return _stub_observation(symbol), f"observation_io_error: {exc}"
    except Exception as exc:  # noqa: BLE001 — factual fallback for malformed parquet
        return (
            _stub_observation(symbol),
            f"observation_unexpected: {type(exc).__name__}: {exc}",
        )

    try:
        observations = build_observations(data)
        text = format_observations(observations)
    except Exception as exc:  # noqa: BLE001
        return (
            _stub_observation(symbol),
            f"observation_render_error: {type(exc).__name__}: {exc}",
        )
    return text, None


def _stub_observation(symbol: str) -> str:
    return (
        f"[{_now_timestamp()}]\n\n"
        f"SYMBOL: {symbol or NA}\n\n"
        f"OBSERVATION: {NA}\n"
    )


def _format_news_section(result: NewsResult) -> str:
    lines: list[str] = []
    lines.append("NEWS")
    lines.append("")
    lines.append(f"[{result.timestamp}]")
    lines.append("")
    lines.append(f"SYMBOL: {result.symbol or NA}")
    lines.append(f"COUNT: {result.count}")
    if result.error:
        lines.append(f"ERROR: {result.error}")
    lines.append("")

    if not result.items:
        lines.append("Source:")
        lines.append(NA)
        lines.append("")
        lines.append("Headline:")
        lines.append(NA)
        lines.append("")
        lines.append("URL:")
        lines.append(NA)
        lines.append("")
        lines.append(SECTION_RULE)
        return "\n".join(lines) + "\n"

    for item in result.items:
        lines.append("Source:")
        lines.append(item.source if item.source else NA)
        lines.append("")
        lines.append("Headline:")
        lines.append(item.headline if item.headline else NA)
        lines.append("")
        lines.append("URL:")
        lines.append(item.url if item.url else NA)
        lines.append("")
        lines.append(SECTION_RULE)
        lines.append("")

    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines) + "\n"


def render_workspace(
    symbol: str,
    *,
    lookback: int = 5,
    news_limit: int = 5,
    news_timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> str:
    """Render the unified workspace block for one symbol.

    Sections are always separate and printed in the order ``OBSERVATION``
    then ``NEWS``. Any failure in either section is rendered factually
    (token in `ERROR:` / `OBSERVATION: Not Available`) — both sections are
    always emitted.
    """
    observation_text, _obs_error = _build_observation_section(symbol, lookback)
    news_result = fetch_symbol_news(symbol, limit=news_limit, timeout=news_timeout)
    news_text = _format_news_section(news_result)
    if not observation_text.endswith("\n"):
        observation_text += "\n"
    return f"{observation_text}\n{SECTION_RULE}\n\n{news_text}"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    _reconfigure_stdout_utf8()
    parser = argparse.ArgumentParser(
        prog="workspace",
        description="MM.AI unified factual workspace — observations + live headline links.",
    )
    parser.add_argument("symbol", help="Symbol, e.g. RELIANCE")
    parser.add_argument(
        "--lookback",
        type=int,
        default=5,
        help="Number of sessions per segment for the observation block (default: 5).",
    )
    parser.add_argument(
        "--news-limit",
        type=int,
        default=5,
        help="Maximum number of headlines to render (default: 5).",
    )
    parser.add_argument(
        "--news-timeout",
        type=float,
        default=DEFAULT_TIMEOUT_SECONDS,
        help=f"News HTTP timeout in seconds (default: {DEFAULT_TIMEOUT_SECONDS}).",
    )
    args = parser.parse_args(argv)

    raw_symbol = (args.symbol or "").strip()
    if not raw_symbol:
        print("error: blank symbol", file=sys.stderr)
        return 2
    if args.lookback < 1:
        print("error: --lookback must be >= 1", file=sys.stderr)
        return 2
    if args.news_limit < 1:
        print("error: --news-limit must be >= 1", file=sys.stderr)
        return 2
    if args.news_timeout <= 0:
        print("error: --news-timeout must be > 0", file=sys.stderr)
        return 2

    text = render_workspace(
        raw_symbol,
        lookback=args.lookback,
        news_limit=args.news_limit,
        news_timeout=args.news_timeout,
    )
    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
