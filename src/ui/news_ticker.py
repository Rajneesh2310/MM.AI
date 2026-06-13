"""Auto-scrolling news ticker for the MM.AI workspace.

Drives a ``QTextBrowser`` so the news block scrolls continuously upward
without manual scrollbars. The ticker pauses while the cursor is over the
news view so the user can read and click the live URLs, then resumes on
mouse leave. When the bottom is reached the view briefly holds, jumps back
to the top, and the crawl continues.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QTimer
from PySide6.QtWidgets import QTextBrowser


class NewsTicker(QObject):
    """Continuous upward scroll of a QTextBrowser. Hover pauses the crawl."""

    PIXELS_PER_TICK = 1
    INTERVAL_MS = 60
    BOTTOM_HOLD_TICKS = 25
    TOP_HOLD_TICKS = 12

    def __init__(self, view: QTextBrowser) -> None:
        super().__init__(view)
        self._view = view
        self._timer = QTimer(self)
        self._timer.setInterval(self.INTERVAL_MS)
        self._timer.timeout.connect(self._tick)
        self._paused = False
        self._hold = 0
        view.setMouseTracking(True)
        view.installEventFilter(self)
        view.viewport().installEventFilter(self)

    # ---- public API ------------------------------------------------------

    def start(self) -> None:
        if not self._timer.isActive():
            self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def restart_from_top(self) -> None:
        sb = self._view.verticalScrollBar()
        sb.setValue(0)
        self._hold = self.TOP_HOLD_TICKS
        self.start()

    def is_paused(self) -> bool:
        return self._paused

    # ---- internals -------------------------------------------------------

    def eventFilter(self, obj, event) -> bool:  # type: ignore[override]
        et = event.type()
        if et == QEvent.Type.Enter:
            self._paused = True
        elif et == QEvent.Type.Leave:
            self._paused = False
        return False

    def _tick(self) -> None:
        if self._paused:
            return
        sb = self._view.verticalScrollBar()
        if sb.maximum() == 0:
            return
        if self._hold > 0:
            self._hold -= 1
            return
        new_val = sb.value() + self.PIXELS_PER_TICK
        if new_val >= sb.maximum():
            sb.setValue(sb.maximum())
            self._hold = self.BOTTOM_HOLD_TICKS
            QTimer.singleShot(
                self.INTERVAL_MS * self.BOTTOM_HOLD_TICKS,
                lambda: sb.setValue(0),
            )
            return
        sb.setValue(new_val)
