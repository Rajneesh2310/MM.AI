"""UI integration tests for symbol autocomplete + picker fallback.

Covers:
- ``set_symbol_catalogue`` populates the completer's model.
- Last-token completer splits on ``,`` so multi-symbol input still completes.
- WorkspaceController.resolve_symbols passes through known tokens.
- Unknown tokens trigger the picker; selection replaces the token.
- Picker cancellation drops the token.
- Mix of known + unknown is handled correctly.
- Catalogue absence (no MM cache) gracefully degrades to pass-through.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication

from src import symbol_catalog
from src.ui.main_window import MainWindow
from src.workspace_window import WorkspaceController, parse_symbols


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication(sys.argv)
    yield app


@pytest.fixture
def fake_install(tmp_path, monkeypatch):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "cash_symbols.json").write_text(
        json.dumps(["RELIANCE", "INFY", "TCS", "RELIGARE", "RELINFRA"]),
        encoding="utf-8",
    )
    (tmp_path / "data" / "fo_symbols.json").write_text(
        json.dumps(["NIFTY", "BANKNIFTY", "RELIANCE"]),
        encoding="utf-8",
    )
    monkeypatch.setenv("MM_INSTALL_ROOT", str(tmp_path))
    symbol_catalog.clear_cache()
    yield tmp_path
    symbol_catalog.clear_cache()


# ---------------------------------------------------------------------------
# QCompleter wiring
# ---------------------------------------------------------------------------


def test_main_window_completer_populated_from_catalogue(qapp, fake_install):
    win = MainWindow()
    win.set_symbol_catalogue(symbol_catalog.list_all_symbols())
    completer = win.completer()
    model = completer.model()
    assert model is not None
    items = [model.data(model.index(i, 0)) for i in range(model.rowCount())]
    for expected in ("RELIANCE", "INFY", "TCS", "NIFTY", "BANKNIFTY"):
        assert expected in items
    win.close()


def test_completer_splits_on_last_comma(qapp, fake_install):
    """``splitPath`` returns the trailing token only — the prefix is ignored
    for the lookup so multi-symbol input keeps working."""
    win = MainWindow()
    win.set_symbol_catalogue(["RELIANCE", "INFY", "NIFTY"])
    completer = win.completer()
    tail = completer.splitPath("RELIANCE, IN")
    assert tail == ["IN"]
    win.close()


def test_completer_assembles_path_with_existing_prefix(qapp, fake_install):
    """``pathFromIndex`` re-prepends everything before the last comma."""
    win = MainWindow()
    win.set_symbol_catalogue(["RELIANCE", "INFY"])
    completer = win.completer()
    win.symbol_field().setText("RELIANCE, IN")

    model = completer.model()
    idx = None
    for i in range(model.rowCount()):
        if model.data(model.index(i, 0)) == "INFY":
            idx = model.index(i, 0)
            break
    assert idx is not None
    assert completer.pathFromIndex(idx) == "RELIANCE, INFY"
    win.close()


# ---------------------------------------------------------------------------
# Controller resolution
# ---------------------------------------------------------------------------


def _picker_choose(chosen):
    """Picker double that returns the given symbol as 'accepted'."""

    def factory(query, candidates, parent):
        return chosen, True

    return factory


def _picker_cancel(_=None):
    """Picker double that always returns 'cancelled'."""

    def factory(query, candidates, parent):
        return None, False

    return factory


def test_resolve_passes_known_symbols_through(qapp, fake_install):
    win = MainWindow()
    ctrl = WorkspaceController(win)

    called = {"count": 0}

    def picker(query, candidates, parent):
        called["count"] += 1
        return None, False

    ctrl.set_picker_factory(picker)
    out = ctrl.resolve_symbols(parse_symbols("RELIANCE, INFY, NIFTY"))
    assert out == ["RELIANCE", "INFY", "NIFTY"]
    assert called["count"] == 0  # picker never invoked for known tokens
    win.close()


def test_resolve_invokes_picker_for_unknown_and_uses_choice(qapp, fake_install):
    win = MainWindow()
    ctrl = WorkspaceController(win)
    captured = {}

    def picker(query, candidates, parent):
        captured["query"] = query
        captured["candidates"] = list(candidates)
        return "RELIANCE", True

    ctrl.set_picker_factory(picker)
    out = ctrl.resolve_symbols(parse_symbols("RELIANC"))
    assert out == ["RELIANCE"]
    assert captured["query"] == "RELIANC"
    assert "RELIANCE" in captured["candidates"]
    win.close()


def test_resolve_drops_cancelled_token(qapp, fake_install):
    win = MainWindow()
    ctrl = WorkspaceController(win)
    ctrl.set_picker_factory(_picker_cancel())
    out = ctrl.resolve_symbols(parse_symbols("ZZZZNOTREAL"))
    assert out == []
    win.close()


def test_resolve_mixed_known_unknown_with_partial_acceptance(qapp, fake_install):
    win = MainWindow()
    ctrl = WorkspaceController(win)

    calls = []

    def picker(query, candidates, parent):
        calls.append(query)
        # Accept the first unknown ("RELIANC" -> RELIANCE),
        # cancel the second ("ZZZZNOTREAL").
        if query == "RELIANC":
            return "RELIANCE", True
        return None, False

    ctrl.set_picker_factory(picker)
    out = ctrl.resolve_symbols(parse_symbols("RELIANC, INFY, ZZZZNOTREAL"))
    assert out == ["RELIANCE", "INFY"]
    assert calls == ["RELIANC", "ZZZZNOTREAL"]
    win.close()


def test_resolve_dedups_after_picker_substitution(qapp, fake_install):
    """If the picker resolves an unknown to a symbol the user *also* typed
    explicitly, the duplicate is collapsed."""
    win = MainWindow()
    ctrl = WorkspaceController(win)

    ctrl.set_picker_factory(_picker_choose("RELIANCE"))
    out = ctrl.resolve_symbols(parse_symbols("RELIANC, RELIANCE"))
    assert out == ["RELIANCE"]
    win.close()


def test_resolve_passes_through_when_catalogue_empty(
    qapp, tmp_path, monkeypatch
):
    """When MM's cache files don't exist on this machine the catalogue is
    empty and we must not pop a picker for every token — let the parquet
    reader fail later as usual."""
    monkeypatch.setenv("MM_INSTALL_ROOT", str(tmp_path / "no-data"))
    symbol_catalog.clear_cache()

    win = MainWindow()
    ctrl = WorkspaceController(win)

    def picker(*_a, **_kw):
        raise AssertionError("picker must not be invoked when catalogue empty")

    ctrl.set_picker_factory(picker)
    out = ctrl.resolve_symbols(parse_symbols("RELIANCE, MADE_UP"))
    assert out == ["RELIANCE", "MADE_UP"]
    win.close()
    symbol_catalog.clear_cache()
