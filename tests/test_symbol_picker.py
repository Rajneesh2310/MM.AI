"""Headless tests for the SymbolPickerDialog widget."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication, QDialog, QDialogButtonBox

from src.ui.symbol_picker import SymbolPickerDialog


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication(sys.argv)
    yield app


def test_dialog_lists_candidates(qapp):
    dlg = SymbolPickerDialog(
        "RELIANC", ["RELIANCE", "RELIANCEPP", "RELIGARE"], parent=None
    )
    assert dlg.candidates == ("RELIANCE", "RELIANCEPP", "RELIGARE")
    items = [
        dlg._list_widget.item(i).text() for i in range(dlg._list_widget.count())
    ]
    assert items == ["RELIANCE", "RELIANCEPP", "RELIGARE"]
    assert dlg.selected_symbol() == "RELIANCE"  # first row pre-selected


def test_dialog_accept_returns_selected(qapp):
    dlg = SymbolPickerDialog("REL", ["RELIANCE", "RELIGARE"], parent=None)
    dlg._list_widget.setCurrentRow(1)
    dlg.accept()
    assert dlg.result() == QDialog.DialogCode.Accepted
    assert dlg.selected_symbol() == "RELIGARE"


def test_dialog_reject_returns_no_selection_state(qapp):
    dlg = SymbolPickerDialog("REL", ["RELIANCE"], parent=None)
    dlg.reject()
    assert dlg.result() == QDialog.DialogCode.Rejected


def test_dialog_disables_ok_when_no_candidates(qapp):
    dlg = SymbolPickerDialog("ZZZ_NOMATCH", [], parent=None)
    btn_box = dlg.findChild(QDialogButtonBox, "SymbolPickerButtons")
    assert btn_box is not None
    ok_btn = btn_box.button(QDialogButtonBox.StandardButton.Ok)
    assert ok_btn is not None
    assert ok_btn.isEnabled() is False
    assert dlg.selected_symbol() is None


def test_dialog_dedups_blank_candidates(qapp):
    dlg = SymbolPickerDialog(
        "REL", ["RELIANCE", "", None, "RELIGARE"], parent=None  # type: ignore[list-item]
    )
    assert dlg.candidates == ("RELIANCE", "RELIGARE")


def test_dialog_double_click_accepts(qapp):
    dlg = SymbolPickerDialog("REL", ["RELIANCE", "RELIGARE"], parent=None)
    dlg._list_widget.setCurrentRow(1)
    item = dlg._list_widget.item(1)
    dlg._list_widget.itemDoubleClicked.emit(item)
    assert dlg.result() == QDialog.DialogCode.Accepted
    assert dlg.selected_symbol() == "RELIGARE"
