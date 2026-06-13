"""Live validation harness for the symbol-search adapter.

Loads MM's real ``cash_symbols.json`` + ``fo_symbols.json`` (read-only) and
exercises :func:`src.symbol_catalog.find_matches` over a fixed set of
realistic queries — exact hit, partial prefix, typo, contains, empty.

Also checks the UI integration end-to-end (offscreen):
- ``MainWindow.set_symbol_catalogue`` accepts the live catalogue.
- ``WorkspaceController.resolve_symbols`` resolves a known + an unknown
  token using an injected picker that always picks the first candidate.

Output is a single JSON document on stdout — consumed by
``MM.AI/symbol-search-report.md``.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    _reconfigure = getattr(_stream, "reconfigure", None)
    if callable(_reconfigure):
        try:
            _reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication

from src import config, symbol_catalog
from src.ui.main_window import MainWindow
from src.workspace_window import WorkspaceController, parse_symbols


QUERIES = [
    "RELIANCE",     # exact
    "RELIAN",       # prefix only
    "RELIANC",      # one-char typo / truncation
    "BANK",         # contains-heavy
    "INPFY",        # transposition typo
    "NIF",          # short prefix matching index
    "ZZZ_NOTREAL",  # no match at all
    "",             # empty input
]


def _file_meta(path: Path) -> dict:
    if not path.is_file():
        return {"path": str(path), "exists": False, "size_bytes": 0}
    return {
        "path": str(path),
        "exists": True,
        "size_bytes": path.stat().st_size,
    }


def main() -> int:
    symbol_catalog.clear_cache()

    data_root = config.data_root()
    cash_cache = data_root / "cash_symbols.json"
    fo_cache = data_root / "fo_symbols.json"

    cash = symbol_catalog.list_cash_symbols()
    fo = symbol_catalog.list_fo_symbols()
    union = symbol_catalog.list_all_symbols()

    matches: list[dict] = []
    for q in QUERIES:
        hits = symbol_catalog.find_matches(q, limit=8)
        matches.append(
            {
                "query": q,
                "exact_match_present": q.upper() in set(union),
                "match_count": len(hits),
                "matches": hits,
            }
        )

    # UI sanity
    app = QApplication.instance() or QApplication(sys.argv)
    win = MainWindow()
    win.set_symbol_catalogue(union)
    completer = win.completer()
    completer_count = completer.model().rowCount() if completer.model() else 0

    ctrl = WorkspaceController(win)

    picker_log: list[dict] = []

    def picker(query, candidates, parent):
        picker_log.append(
            {"query": query, "candidates": list(candidates)[:8]}
        )
        return candidates[0] if candidates else None, bool(candidates)

    ctrl.set_picker_factory(picker)

    raw_input = "RELIANCE, RELIANC, ZZZ_NOTREAL"
    resolved = ctrl.resolve_symbols(parse_symbols(raw_input))

    win.close()
    app.processEvents()

    out = {
        "install_root": str(config.install_root()),
        "cash_cache": _file_meta(cash_cache),
        "fo_cache": _file_meta(fo_cache),
        "counts": {
            "cash_symbols": len(cash),
            "fo_symbols": len(fo),
            "union_symbols": len(union),
        },
        "ui_completer_row_count": completer_count,
        "fuzzy_match_queries": matches,
        "ui_resolution": {
            "input": raw_input,
            "parsed": parse_symbols(raw_input),
            "resolved": resolved,
            "picker_calls": picker_log,
        },
    }
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
