"""Headless themed validation — UX Step 2.

Boots a real ``QApplication`` with the dark theme applied, drives the
required symbol sets through ``run_pipeline``, pushes results into a real
``MainWindow``, and prints a factual JSON summary for the UX report.
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

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from src.ui.main_window import MainWindow  # noqa: E402
from src.ui.theme import PALETTE, apply_theme  # noqa: E402
from src.workspace_window import (  # noqa: E402
    create_workspace_window,
    parse_symbols,
    run_pipeline,
)

CASES = [
    ("single_RELIANCE", "RELIANCE"),
    ("single_INFY", "INFY"),
    ("single_NIFTY", "NIFTY"),
    ("multi_3", "RELIANCE, INFY, NIFTY"),
    ("multi_with_unknown", "RELIANCE, NONEXISTENT_SYM_123"),
]

ANCHOR_RE = re.compile(r'<a\s+href="([^"]+)"[^>]*>')


def _scrape_table_value(html: str, parameter: str, symbol_index: int, kind: str) -> str | None:
    """Best-effort scrape of `<td>` for (parameter, symbol_index, kind)."""
    # find row for parameter
    row_match = re.search(
        rf'<tr><td class="param">{re.escape(parameter)}</td>(.*?)</tr>',
        html,
        re.DOTALL,
    )
    if not row_match:
        return None
    row_html = row_match.group(1)
    cells = re.findall(r'<td class="num[^"]*">([^<]*)</td>', row_html)
    base = symbol_index * 3
    offset = {"prev": 0, "latest": 1, "delta": 2}[kind]
    idx = base + offset
    if idx >= len(cells):
        return None
    return cells[idx]


def main() -> int:
    app = QApplication.instance() or QApplication([])
    apply_theme(app)
    qss = app.styleSheet()
    qss_facts = {
        "qss_length": len(qss),
        "ui_font": app.font().family(),
        "ui_font_size": app.font().pointSize(),
        "accent_in_qss": PALETTE["accent"] in qss,
    }

    rows: list[dict] = []
    for case_name, raw in CASES:
        window, _ctl = create_workspace_window()
        window.resize(1200, 800)
        window.show()
        app.processEvents()
        try:
            symbols = parse_symbols(raw)
            obs_html, news_html, news_results = run_pipeline(
                raw, lookback=5, news_limit=5, news_timeout=8.0
            )
            window.set_observation_html(obs_html)
            window.set_news_html(news_html)
            window.symbol_field().setText(raw)
            window.set_status(f"loaded {len(symbols)} symbol(s)")
            app.processEvents()
            app.processEvents()
            # Inspect view widgets after rendering.
            obs_view = window.findChild(object, "ObservationView")
            news_view = window.findChild(object, "NewsView")

            entry = {
                "case": case_name,
                "raw_input": raw,
                "parsed_symbols": symbols,
                "obs_html_len": len(obs_html),
                "obs_plain_chars": len(window.observation_plain_text()),
                "obs_has_cash_header": "CASH" in obs_html,
                "obs_has_fo_header": "F&amp;O" in obs_html,
                "obs_has_row_count_text": "Row Count" in obs_html,
                "obs_h_scroll_policy": str(obs_view.horizontalScrollBarPolicy()),
                "obs_v_scroll_policy": str(obs_view.verticalScrollBarPolicy()),
                "obs_h_scroll_max": obs_view.horizontalScrollBar().maximum(),
                "obs_v_scroll_max": obs_view.verticalScrollBar().maximum(),
                "news_v_scroll_policy": str(news_view.verticalScrollBarPolicy()),
                "news_h_scroll_policy": str(news_view.horizontalScrollBarPolicy()),
                "news_anchor_count": len(ANCHOR_RE.findall(news_html)),
                "news_per_symbol_counts": [r.count for r in news_results],
                "news_errors": [r.error for r in news_results],
                "ticker_timer_active": window.news_ticker()._timer.isActive(),
                "table_close_latest": [
                    _scrape_table_value(obs_html, "Close", i, "latest")
                    for i in range(len(symbols))
                ],
                "table_close_delta": [
                    _scrape_table_value(obs_html, "Close", i, "delta")
                    for i in range(len(symbols))
                ],
                "table_oi_latest": [
                    _scrape_table_value(obs_html, "OI Total", i, "latest")
                    for i in range(len(symbols))
                ],
            }
            rows.append(entry)
        finally:
            window.close()

    print(json.dumps({"qss": qss_facts, "rows": rows}, indent=2, ensure_ascii=False))
    app.quit()
    return 0


if __name__ == "__main__":
    sys.exit(main())
