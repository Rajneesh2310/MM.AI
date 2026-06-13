"""Headless end-to-end validation for the UI report.

Drives the same code path the desktop UI uses (``run_pipeline`` + main window
setters) against the real MM parquet root for the four required symbols, then
emits a compact factual JSON summary on stdout for use in the report.

This script is not a pytest test — it requires a populated MM data root.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

for _stream in (sys.stdout, sys.stderr):
    _reconfigure = getattr(_stream, "reconfigure", None)
    if callable(_reconfigure):
        try:
            _reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication  # noqa: E402

from src.ui.main_window import MainWindow  # noqa: E402
from src.workspace_window import run_pipeline  # noqa: E402

SYMBOLS = ["RELIANCE", "INFY", "NIFTY", "NONEXISTENT_SYM_123"]
ANCHOR_RE = re.compile(r'<a\s+href="([^"]+)"')


def _extract(obs_text: str, label: str) -> str:
    pattern = re.compile(rf"^{re.escape(label)}:\n(.+)$", re.MULTILINE)
    m = pattern.search(obs_text)
    return m.group(1).strip() if m else ""


def _grade_obs(obs_text: str) -> dict:
    return {
        "symbol_line_present": bool(re.search(r"^SYMBOL:\s+\S", obs_text, re.MULTILINE)),
        "timestamp_line_present": bool(
            re.search(r"^\[\d{2}:\d{2}:\d{2} \d{2}:\d{2}:\d{2}\]$", obs_text, re.MULTILINE)
        ),
        "cash_header_present": "CASH" in obs_text,
        "fo_header_present": "F&O" in obs_text,
        "latest_session_cash": _extract(obs_text, "Latest Session") or None,
        "latest_close": _extract(obs_text, "Latest Close") or None,
        "close_delta": _extract(obs_text, "Close Delta") or None,
        "latest_oi_total": _extract(obs_text, "Latest OI Total") or None,
        "char_count": len(obs_text),
    }


def main() -> int:
    app = QApplication.instance() or QApplication([])
    rows: list[dict] = []
    for sym in SYMBOLS:
        window = MainWindow()
        try:
            obs_text, news_html, news_result = run_pipeline(
                sym, lookback=5, news_limit=5, news_timeout=8.0
            )
            window.set_observation_text(obs_text)
            window.set_news_html(news_html)
            anchors = ANCHOR_RE.findall(news_html)
            grade = _grade_obs(obs_text)
            row = {
                "symbol": sym,
                "obs": grade,
                "ui_observation_chars": len(window.observation_text()),
                "ui_news_html_chars": len(window.news_html()),
                "news_count": news_result.count,
                "news_error": news_result.error,
                "news_first_source": news_result.items[0].source if news_result.items else None,
                "news_first_headline": (
                    news_result.items[0].headline if news_result.items else None
                ),
                "news_first_url": news_result.items[0].url if news_result.items else None,
                "anchor_count": len(anchors),
                "anchor_first": anchors[0] if anchors else None,
            }
            rows.append(row)
        finally:
            window.close()
    print(json.dumps(rows, indent=2, ensure_ascii=False))
    app.quit()
    return 0


if __name__ == "__main__":
    sys.exit(main())
