"""Modal picker dialog for resolving unknown / partial symbols.

Shown by :mod:`src.workspace_window` when the user submits a token that
isn't present in the MM symbol catalogue. The dialog displays the top N
candidates returned by :func:`src.symbol_catalog.find_matches` and lets
the user pick one (or cancel, in which case the token is dropped).

Styling consumes the same palette as the rest of the UI via
:mod:`src.ui.theme` — no hard-coded colours here.
"""

from __future__ import annotations

from typing import Iterable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)


class SymbolPickerDialog(QDialog):
    """Lightweight pick-one-or-cancel dialog over a small candidate list."""

    def __init__(
        self,
        query: str,
        candidates: Iterable[str],
        *,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("SymbolPickerDialog")
        self.setWindowTitle("Symbol not found")
        self.setModal(True)
        self.setMinimumWidth(360)

        self._query = (query or "").strip()
        cand_list = [c for c in candidates if c]
        self._candidates: tuple[str, ...] = tuple(cand_list)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        if self._candidates:
            prompt = (
                f"No exact match for <b>{self._query or '(blank)'}</b>. "
                f"Did you mean one of these?"
            )
        else:
            prompt = (
                f"No matches found for <b>{self._query or '(blank)'}</b>. "
                f"Press Cancel to skip this symbol."
            )
        prompt_label = QLabel(prompt)
        prompt_label.setObjectName("SymbolPickerPrompt")
        prompt_label.setWordWrap(True)
        layout.addWidget(prompt_label)

        self._list_widget = QListWidget(self)
        self._list_widget.setObjectName("SymbolPickerList")
        self._list_widget.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self._list_widget.setUniformItemSizes(True)
        for sym in self._candidates:
            item = QListWidgetItem(sym, self._list_widget)
            item.setData(Qt.ItemDataRole.UserRole, sym)
        if self._candidates:
            self._list_widget.setCurrentRow(0)
        layout.addWidget(self._list_widget, stretch=1)

        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        button_box.setObjectName("SymbolPickerButtons")
        ok_btn = button_box.button(QDialogButtonBox.StandardButton.Ok)
        if ok_btn is not None:
            ok_btn.setText("Use Selected")
            ok_btn.setEnabled(bool(self._candidates))
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

        self._list_widget.itemDoubleClicked.connect(lambda _item: self.accept())

    @property
    def candidates(self) -> tuple[str, ...]:
        return self._candidates

    def selected_symbol(self) -> str | None:
        """Return the currently selected symbol, or ``None`` if none chosen."""
        item = self._list_widget.currentItem()
        if item is None:
            return None
        value = item.data(Qt.ItemDataRole.UserRole)
        return str(value) if value else None
