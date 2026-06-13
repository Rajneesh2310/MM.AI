"""Bloomberg-style "Talk to Market" panel.

Pure UI — no business logic. Owns:

- A multiline question input (``QPlainTextEdit`` subclass) where Enter
  submits the question and Shift+Enter inserts a newline.
- A subtle "Examples:" helper line below the input.
- A right-aligned ``Talk`` button.
- A "MARKET RESPONSE" header with the render timestamp and two small
  ``Clear`` / ``Copy`` buttons.
- A monospaced response panel (``QPlainTextEdit``, read-only, selectable).

Signals:

- ``talk_requested(str)``         — user submitted a question.
- ``clear_response_requested()``  — Clear pressed (panel already cleared).
- ``copy_response_requested(str)`` — Copy pressed (already copied to
  ``QApplication.clipboard``); the text is forwarded for diagnostics.

Styling is driven from :mod:`src.ui.theme` via object names and dynamic
``kind`` properties (``ok`` / ``error`` / ``fallback``).
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QGuiApplication, QKeyEvent
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .theme import mono_font

EXAMPLES_TEXT = (
    "Examples:  "
    'What changed in RELIANCE today?  |  '
    "Compare RELIANCE and INFY  |  "
    "Why is NIFTY in news?"
)

QUESTION_PLACEHOLDER = (
    'Ask a market question, e.g. "What changed in RELIANCE today?"'
)


class _TalkQuestionEdit(QPlainTextEdit):
    """``QPlainTextEdit`` where Enter submits and Shift+Enter inserts a newline."""

    submit_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setTabChangesFocus(True)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # type: ignore[override]
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                super().keyPressEvent(event)
                return
            if not self.isReadOnly() and self.isEnabled():
                self.submit_requested.emit()
                event.accept()
                return
        super().keyPressEvent(event)


class TalkToMarketWidget(QWidget):
    """Talk to Market UI block. Lives inside the workspace splitter."""

    talk_requested = Signal(str)
    clear_response_requested = Signal()
    copy_response_requested = Signal(str)

    QUESTION_INPUT_MIN_HEIGHT = 56
    QUESTION_INPUT_MAX_HEIGHT = 90

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("TalkHolder")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(4)

        outer.addWidget(self._build_section_header())
        outer.addLayout(self._build_question_row())
        outer.addWidget(self._build_examples())
        outer.addLayout(self._build_response_header())
        outer.addWidget(self._build_response_view(), stretch=1)

    # ---- builders -------------------------------------------------------

    def _build_section_header(self) -> QWidget:
        label = QLabel("TALK TO MARKET")
        label.setObjectName("SectionLabel")
        return label

    def _build_question_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)

        self._question_input = _TalkQuestionEdit(self)
        self._question_input.setObjectName("TalkQuestionInput")
        self._question_input.setPlaceholderText(QUESTION_PLACEHOLDER)
        self._question_input.setFont(mono_font())
        self._question_input.setMinimumHeight(self.QUESTION_INPUT_MIN_HEIGHT)
        self._question_input.setMaximumHeight(self.QUESTION_INPUT_MAX_HEIGHT)
        self._question_input.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self._question_input.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._question_input.submit_requested.connect(self._on_submit)
        row.addWidget(self._question_input, stretch=1)

        button_col = QVBoxLayout()
        button_col.setContentsMargins(0, 0, 0, 0)
        button_col.setSpacing(4)
        self._talk_button = QPushButton("Talk")
        self._talk_button.setObjectName("TalkButton")
        self._talk_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._talk_button.setMinimumWidth(96)
        self._talk_button.clicked.connect(self._on_submit)
        button_col.addWidget(self._talk_button)
        button_col.addStretch()
        row.addLayout(button_col)
        return row

    def _build_examples(self) -> QWidget:
        self._examples_label = QLabel(EXAMPLES_TEXT)
        self._examples_label.setObjectName("TalkExamples")
        self._examples_label.setWordWrap(False)
        self._examples_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        return self._examples_label

    def _build_response_header(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(0, 4, 0, 0)
        row.setSpacing(8)

        header = QLabel("MARKET RESPONSE")
        header.setObjectName("TalkResponseHeader")
        row.addWidget(header, alignment=Qt.AlignmentFlag.AlignLeft)

        self._timestamp_label = QLabel("")
        self._timestamp_label.setObjectName("TalkResponseTimestamp")
        row.addWidget(
            self._timestamp_label, alignment=Qt.AlignmentFlag.AlignLeft
        )

        row.addStretch()

        self._clear_button = QPushButton("Clear")
        self._clear_button.setObjectName("TalkSmallButton")
        self._clear_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._clear_button.clicked.connect(self._on_clear)
        row.addWidget(self._clear_button)

        self._copy_button = QPushButton("Copy")
        self._copy_button.setObjectName("TalkSmallButton")
        self._copy_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._copy_button.clicked.connect(self._on_copy)
        row.addWidget(self._copy_button)

        return row

    def _build_response_view(self) -> QWidget:
        self._response_view = QPlainTextEdit(self)
        self._response_view.setObjectName("TalkResponseView")
        self._response_view.setReadOnly(True)
        self._response_view.setFont(mono_font())
        self._response_view.setLineWrapMode(
            QPlainTextEdit.LineWrapMode.WidgetWidth
        )
        self._response_view.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.TextSelectableByKeyboard
        )
        return self._response_view

    # ---- internal slots --------------------------------------------------

    def _on_submit(self) -> None:
        if not self._talk_button.isEnabled():
            return
        question = self._question_input.toPlainText().strip()
        self.talk_requested.emit(question)

    def _on_clear(self) -> None:
        self._response_view.clear()
        self._timestamp_label.setText("")
        self._set_response_kind(None)
        self.clear_response_requested.emit()

    def _on_copy(self) -> None:
        text = self._response_view.toPlainText()
        clipboard = QGuiApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(text)
        self.copy_response_requested.emit(text)

    def _set_response_kind(self, kind: str | None) -> None:
        self._response_view.setProperty("kind", kind or "")
        style = self._response_view.style()
        if style is not None:
            style.unpolish(self._response_view)
            style.polish(self._response_view)

    # ---- public API ------------------------------------------------------

    def set_response(
        self,
        text: str,
        timestamp: str,
        *,
        kind: str = "ok",
    ) -> None:
        """Render ``text`` in the response panel and stamp the header.

        ``kind`` is one of ``"ok"``, ``"error"``, ``"fallback"`` and drives
        subtle colour shifts via the QSS dynamic-property selector.
        """
        self._response_view.setPlainText(text or "")
        self._timestamp_label.setText(timestamp or "")
        self._set_response_kind(kind)
        self._response_view.verticalScrollBar().setValue(0)

    def clear_response(self) -> None:
        self._on_clear()

    def set_busy(self, busy: bool) -> None:
        """Disable inputs while a response is being generated."""
        self._talk_button.setEnabled(not busy)
        self._question_input.setReadOnly(busy)
        self._question_input.setEnabled(True)  # keep visible but read-only

    def set_question(self, text: str) -> None:
        self._question_input.setPlainText(text or "")

    def clear_question(self) -> None:
        self._question_input.clear()

    # ---- accessors used by tests / controllers --------------------------

    def question_text(self) -> str:
        return self._question_input.toPlainText().strip()

    def response_text(self) -> str:
        return self._response_view.toPlainText()

    def timestamp_text(self) -> str:
        return self._timestamp_label.text()

    def question_input(self) -> _TalkQuestionEdit:
        return self._question_input

    def response_view(self) -> QPlainTextEdit:
        return self._response_view

    def talk_button(self) -> QPushButton:
        return self._talk_button

    def clear_button(self) -> QPushButton:
        return self._clear_button

    def copy_button(self) -> QPushButton:
        return self._copy_button

    def examples_label(self) -> QLabel:
        return self._examples_label

    def response_kind(self) -> str:
        kind = self._response_view.property("kind")
        return str(kind) if kind else ""

    def is_busy(self) -> bool:
        return not self._talk_button.isEnabled()
