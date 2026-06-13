"""Headless tests for the Talk to Market widget.

Validates:
- Section labels and placeholder text use the exact spec wording.
- Enter inside the question input emits ``talk_requested``.
- Shift+Enter inserts a newline and does NOT submit.
- Talk button click submits the trimmed question text.
- ``Clear`` empties the response panel + timestamp and emits the signal.
- ``Copy`` puts the response text on the clipboard and emits the signal.
- ``set_response`` renders text, timestamp, and the dynamic ``kind`` property.
- ``set_busy`` disables the Talk button and makes the input read-only.
- An empty question still emits the signal (the controller decides what
  to do with it — the widget never silently drops).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from src.ui.talk_widget import (
    EXAMPLES_TEXT,
    QUESTION_PLACEHOLDER,
    TalkToMarketWidget,
)


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication(sys.argv)
    yield app


# ---------------------------------------------------------------------------
# Labels & exact spec wording
# ---------------------------------------------------------------------------


def test_exact_section_labels_and_placeholder(qapp):
    w = TalkToMarketWidget()
    assert (
        w.question_input().placeholderText() == QUESTION_PLACEHOLDER
        == 'Ask a market question, e.g. "What changed in RELIANCE today?"'
    )
    assert w.talk_button().text() == "Talk"
    assert w.clear_button().text() == "Clear"
    assert w.copy_button().text() == "Copy"
    # Forbidden labels must NOT appear anywhere in the widget tree.
    blob = w.examples_label().text() + " " + w.talk_button().text() + " " + w.clear_button().text()
    for forbidden in ("Ask MM.AI", "AI Chat", "Assistant", "Chatbot"):
        assert forbidden not in blob
    w.deleteLater()


def test_examples_helper_text(qapp):
    w = TalkToMarketWidget()
    assert w.examples_label().text() == EXAMPLES_TEXT
    assert "What changed in RELIANCE today?" in EXAMPLES_TEXT
    assert "Compare RELIANCE and INFY" in EXAMPLES_TEXT
    assert "Why is NIFTY in news?" in EXAMPLES_TEXT
    w.deleteLater()


# ---------------------------------------------------------------------------
# Enter / Shift+Enter handling
# ---------------------------------------------------------------------------


def test_enter_submits_question(qapp):
    w = TalkToMarketWidget()
    captured: list[str] = []
    w.talk_requested.connect(captured.append)

    edit = w.question_input()
    edit.setPlainText("What changed in RELIANCE today?")
    QTest.keyClick(edit, Qt.Key.Key_Return)

    assert captured == ["What changed in RELIANCE today?"]
    # Enter must NOT have inserted a newline.
    assert "\n" not in edit.toPlainText()
    w.deleteLater()


def test_shift_enter_inserts_newline_and_does_not_submit(qapp):
    w = TalkToMarketWidget()
    captured: list[str] = []
    w.talk_requested.connect(captured.append)

    edit = w.question_input()
    edit.setPlainText("line one")
    edit.moveCursor(edit.textCursor().MoveOperation.End)
    QTest.keyClick(edit, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
    QTest.keyClicks(edit, "line two")

    assert captured == []
    assert edit.toPlainText() == "line one\nline two"
    w.deleteLater()


def test_enter_on_empty_input_still_emits_for_controller_to_handle(qapp):
    w = TalkToMarketWidget()
    captured: list[str] = []
    w.talk_requested.connect(captured.append)

    edit = w.question_input()
    QTest.keyClick(edit, Qt.Key.Key_Return)

    # The widget forwards the empty payload — the controller decides.
    assert captured == [""]
    w.deleteLater()


def test_talk_button_click_submits(qapp):
    w = TalkToMarketWidget()
    captured: list[str] = []
    w.talk_requested.connect(captured.append)

    w.question_input().setPlainText("  Compare RELIANCE and INFY.  ")
    QTest.mouseClick(w.talk_button(), Qt.MouseButton.LeftButton)

    assert captured == ["Compare RELIANCE and INFY."]
    w.deleteLater()


def test_talk_button_disabled_when_busy(qapp):
    w = TalkToMarketWidget()
    captured: list[str] = []
    w.talk_requested.connect(captured.append)

    w.set_busy(True)
    assert not w.talk_button().isEnabled()
    assert w.is_busy()
    QTest.mouseClick(w.talk_button(), Qt.MouseButton.LeftButton)
    assert captured == []

    w.set_busy(False)
    assert w.talk_button().isEnabled()
    assert not w.is_busy()
    w.deleteLater()


def test_question_input_becomes_read_only_when_busy(qapp):
    w = TalkToMarketWidget()
    captured: list[str] = []
    w.talk_requested.connect(captured.append)

    w.question_input().setPlainText("Why is NIFTY in news?")
    w.set_busy(True)
    QTest.keyClick(w.question_input(), Qt.Key.Key_Return)
    assert captured == []  # Enter must not submit while busy
    w.deleteLater()


# ---------------------------------------------------------------------------
# Response rendering
# ---------------------------------------------------------------------------


def test_set_response_text_timestamp_and_kind(qapp):
    w = TalkToMarketWidget()
    w.set_response("Plain text answer.", "[25:05:26 14:00:00]", kind="ok")
    assert w.response_text() == "Plain text answer."
    assert w.timestamp_text() == "[25:05:26 14:00:00]"
    assert w.response_kind() == "ok"
    w.deleteLater()


def test_set_response_error_kind(qapp):
    w = TalkToMarketWidget()
    w.set_response("timeout", "[25:05:26 14:00:01]", kind="error")
    assert w.response_kind() == "error"
    w.deleteLater()


def test_set_response_fallback_kind(qapp):
    w = TalkToMarketWidget()
    w.set_response(
        "No workspace loaded. Enter a symbol or ask about a symbol directly.",
        "[25:05:26 14:00:02]",
        kind="fallback",
    )
    assert w.response_kind() == "fallback"
    w.deleteLater()


# ---------------------------------------------------------------------------
# Clear
# ---------------------------------------------------------------------------


def test_clear_button_resets_response_and_timestamp(qapp):
    w = TalkToMarketWidget()
    w.set_response("something", "[25:05:26 14:00:03]", kind="ok")
    received = []
    w.clear_response_requested.connect(lambda: received.append("cleared"))

    QTest.mouseClick(w.clear_button(), Qt.MouseButton.LeftButton)

    assert w.response_text() == ""
    assert w.timestamp_text() == ""
    assert received == ["cleared"]
    w.deleteLater()


# ---------------------------------------------------------------------------
# Copy
# ---------------------------------------------------------------------------


def test_copy_button_places_text_on_clipboard(qapp):
    w = TalkToMarketWidget()
    w.set_response("clipboard payload", "[25:05:26 14:00:04]", kind="ok")
    received = []
    w.copy_response_requested.connect(received.append)

    QTest.mouseClick(w.copy_button(), Qt.MouseButton.LeftButton)

    clip = QGuiApplication.clipboard()
    assert clip is not None
    assert clip.text() == "clipboard payload"
    assert received == ["clipboard payload"]
    w.deleteLater()
