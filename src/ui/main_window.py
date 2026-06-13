"""MM.AI single-window desktop UI (PySide6).

Pure-layout widget. Holds no business logic — every load is driven through
the ``load_requested`` signal which the controller in
:mod:`src.workspace_window` connects to the pipeline runner.

UX Step 2 changes:
- Observation panel is now an HTML comparison table (Parameter | Previous |
  Latest | Δ) rendered into a ``QTextBrowser`` with horizontal overflow.
- News panel is a continuously auto-scrolling ticker (``NewsTicker``) with
  no manual scrollbars; hover pauses the crawl so URLs stay clickable.
- ``Load Workspace`` button removed — Enter on any input triggers the load.
- ``Lookback`` and ``News`` spin boxes are compact two-digit fields with
  no step arrows.

Visual styling lives in :mod:`src.ui.theme`; this module only assigns
object names so the global QSS can target each widget.
"""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QStringListModel, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QCompleter,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QSpinBox,
    QSplitter,
    QStatusBar,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from .news_ticker import NewsTicker
from .talk_widget import TalkToMarketWidget
from .theme import STATUS_KIND_FOR_STATE, StatusState, mono_font


class _LastTokenCompleter(QCompleter):
    """Completer that completes only the *last* comma-separated token.

    With multi-symbol input (``"RELIANCE, INFY, NIFT"``) we need Qt's popup to
    match against the trailing fragment after the final comma, not against
    the whole line. ``splitPath`` returns just that fragment; ``pathFromIndex``
    re-assembles the line by replacing the trailing fragment with the chosen
    symbol so the user can keep typing the next comma immediately.
    """

    def splitPath(self, path: str) -> list[str]:  # type: ignore[override]
        tail = (path or "").rsplit(",", 1)[-1]
        return [tail.strip().upper()]

    def pathFromIndex(self, index) -> str:  # type: ignore[override]
        chosen = index.data() or ""
        widget = self.widget()
        current = widget.text() if widget is not None else ""
        if "," in current:
            head, _, _ = current.rpartition(",")
            return f"{head.rstrip()}, {chosen}"
        return chosen

CLOCK_FORMAT = "[%d:%m:%y %H:%M:%S]"
INITIAL_LOOKBACK = 5
INITIAL_NEWS_LIMIT = 5
HEADER_HEIGHT = 44
SPIN_WIDTH = 52


class MainWindow(QMainWindow):
    """Single-window MM.AI workspace UI."""

    load_requested = Signal(str, int, int)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("MMWorkspaceWindow")
        self.setWindowTitle("MM.AI Workspace")
        self.resize(1200, 800)
        self.setMinimumSize(900, 600)

        central = QWidget(self)
        central.setObjectName("WorkspaceRoot")
        outer = QVBoxLayout(central)
        outer.setContentsMargins(8, 6, 8, 6)
        outer.setSpacing(6)

        outer.addWidget(self._build_header())
        outer.addWidget(self._build_search())
        outer.addWidget(self._build_content(), stretch=1)
        self.setCentralWidget(central)

        self._status_bar = QStatusBar(self)
        self._status_bar.setObjectName("WorkspaceStatusBar")
        self.setStatusBar(self._status_bar)
        self.set_status_state(StatusState.READY)

        self._clock_timer = QTimer(self)
        self._clock_timer.setInterval(1000)
        self._clock_timer.timeout.connect(self._tick_clock)
        self._clock_timer.start()
        self._tick_clock()

    # ---- layout ----------------------------------------------------------

    def _build_header(self) -> QWidget:
        header = QWidget()
        header.setObjectName("HeaderBar")
        header.setFixedHeight(HEADER_HEIGHT)
        header.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        row = QHBoxLayout(header)
        row.setContentsMargins(16, 0, 16, 0)
        row.setSpacing(12)

        title = QLabel("MM.AI Workspace")
        title.setObjectName("HeaderTitle")
        row.addWidget(title, alignment=Qt.AlignmentFlag.AlignLeft)
        row.addStretch()

        self._clock_label = QLabel("")
        self._clock_label.setObjectName("HeaderClock")
        row.addWidget(self._clock_label, alignment=Qt.AlignmentFlag.AlignRight)

        self._header_status = QLabel("Ready")
        self._header_status.setObjectName("HeaderStatus")
        row.addWidget(self._header_status, alignment=Qt.AlignmentFlag.AlignRight)
        return header

    def _build_search(self) -> QWidget:
        wrapper = QWidget()
        wrapper.setObjectName("SearchBar")
        row = QHBoxLayout(wrapper)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)

        self._symbol_input = QLineEdit()
        self._symbol_input.setObjectName("SymbolInput")
        self._symbol_input.setPlaceholderText(
            "Enter symbol(s) and press Enter   (e.g. RELIANCE   or   RELIANCE, INFY, NIFTY)"
        )
        self._symbol_input.setClearButtonEnabled(True)
        self._symbol_input.returnPressed.connect(self._emit_load)

        self._completer_model = QStringListModel(self)
        self._completer = _LastTokenCompleter(self._symbol_input)
        self._completer.setModel(self._completer_model)
        self._completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self._completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self._completer.setMaxVisibleItems(10)
        self._symbol_input.setCompleter(self._completer)

        row.addWidget(self._symbol_input, stretch=1)

        lookback_lbl = QLabel("Lookback")
        lookback_lbl.setObjectName("FieldLabel")
        row.addWidget(lookback_lbl)
        self._lookback_input = QSpinBox()
        self._lookback_input.setObjectName("LookbackInput")
        self._lookback_input.setRange(1, 99)
        self._lookback_input.setValue(INITIAL_LOOKBACK)
        self._lookback_input.setFixedWidth(SPIN_WIDTH)
        self._lookback_input.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lookback_input.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self._lookback_input.lineEdit().returnPressed.connect(self._emit_load)
        row.addWidget(self._lookback_input)

        news_lbl = QLabel("News")
        news_lbl.setObjectName("FieldLabel")
        row.addWidget(news_lbl)
        self._news_limit_input = QSpinBox()
        self._news_limit_input.setObjectName("NewsLimitInput")
        self._news_limit_input.setRange(1, 99)
        self._news_limit_input.setValue(INITIAL_NEWS_LIMIT)
        self._news_limit_input.setFixedWidth(SPIN_WIDTH)
        self._news_limit_input.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._news_limit_input.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self._news_limit_input.lineEdit().returnPressed.connect(self._emit_load)
        row.addWidget(self._news_limit_input)

        return wrapper

    def _build_content(self) -> QWidget:
        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.setObjectName("ContentSplitter")
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(4)

        obs_holder = QWidget()
        obs_holder.setObjectName("ObservationHolder")
        obs_layout = QVBoxLayout(obs_holder)
        obs_layout.setContentsMargins(0, 0, 0, 0)
        obs_layout.setSpacing(4)
        obs_label = QLabel("OBSERVATIONS")
        obs_label.setObjectName("SectionLabel")
        obs_layout.addWidget(obs_label)

        self._observation_view = QTextBrowser()
        self._observation_view.setObjectName("ObservationView")
        self._observation_view.setOpenExternalLinks(False)
        self._observation_view.setLineWrapMode(QTextBrowser.LineWrapMode.NoWrap)
        self._observation_view.setFont(mono_font())
        self._observation_view.document().setDocumentMargin(0)
        self._observation_view.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._observation_view.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        obs_layout.addWidget(self._observation_view, stretch=1)

        news_holder = QWidget()
        news_holder.setObjectName("NewsHolder")
        news_layout = QVBoxLayout(news_holder)
        news_layout.setContentsMargins(0, 0, 0, 0)
        news_layout.setSpacing(4)
        news_label = QLabel("NEWS")
        news_label.setObjectName("SectionLabel")
        news_layout.addWidget(news_label)

        self._news_view = QTextBrowser()
        self._news_view.setObjectName("NewsView")
        self._news_view.setOpenExternalLinks(True)
        self._news_view.setFont(mono_font())
        self._news_view.document().setDocumentMargin(4)
        self._news_view.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._news_view.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        news_layout.addWidget(self._news_view, stretch=1)

        self._news_ticker = NewsTicker(self._news_view)

        self._talk_widget = TalkToMarketWidget()

        splitter.addWidget(obs_holder)
        splitter.addWidget(news_holder)
        splitter.addWidget(self._talk_widget)
        splitter.setSizes([380, 160, 260])
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 2)
        return splitter

    # ---- helpers ---------------------------------------------------------

    def _emit_load(self) -> None:
        # Debounce: Qt can emit returnPressed twice for one Enter press inside a
        # QSpinBox; skip while a load is already in flight (inputs disabled).
        if not self._symbol_input.isEnabled():
            return
        symbol = self._symbol_input.text().strip()
        self.load_requested.emit(
            symbol,
            self._lookback_input.value(),
            self._news_limit_input.value(),
        )

    def _tick_clock(self) -> None:
        self._clock_label.setText(datetime.now().strftime(CLOCK_FORMAT))

    # ---- public API used by the controller -------------------------------

    def set_observation_html(self, html: str) -> None:
        self._observation_view.setHtml(html)
        sb = self._observation_view.horizontalScrollBar()
        sb.setValue(0)

    def set_news_html(self, html: str) -> None:
        self._news_view.setHtml(html)
        self._news_ticker.restart_from_top()

    def set_status(self, message: str) -> None:
        self._status_bar.showMessage(message)
        self._header_status.setText(message)

    def set_status_state(
        self,
        state: str,
        message: str | None = None,
        *,
        header_override: str | None = None,
    ) -> None:
        """Show a canonical status state with a subtle colour.

        ``state`` is one of the :class:`~.theme.StatusState` constants and
        drives the QSS ``kind`` dynamic property (``idle``/``busy``/``ok``/
        ``error``) on both the header status label and the status bar.

        Free-form additional context can be supplied via ``message``; it is
        appended after the state token in the status bar.

        ``header_override`` lets callers replace the header text entirely
        — used by the Talk auto-load flow to render the literal
        ``"LOADING NIFTY, RELIANCE..."`` string mandated by the spec.
        """
        token = state or StatusState.READY
        kind = STATUS_KIND_FOR_STATE.get(token, "idle")
        header_text = header_override if header_override is not None else token
        if header_override is not None:
            full = header_override
        elif message:
            full = f"{token}   {message}"
        else:
            full = token
        self._status_bar.showMessage(full)
        self._header_status.setText(header_text)
        for widget in (self._header_status, self._status_bar):
            widget.setProperty("kind", kind)
            style = widget.style()
            if style is not None:
                style.unpolish(widget)
                style.polish(widget)

    def set_load_enabled(self, enabled: bool) -> None:
        self._symbol_input.setEnabled(enabled)
        self._lookback_input.setEnabled(enabled)
        self._news_limit_input.setEnabled(enabled)

    def talk_widget(self) -> TalkToMarketWidget:
        return self._talk_widget

    # ---- test/inspection accessors --------------------------------------

    def observation_html(self) -> str:
        return self._observation_view.toHtml()

    def observation_plain_text(self) -> str:
        return self._observation_view.toPlainText()

    def news_html(self) -> str:
        return self._news_view.toHtml()

    def news_plain_text(self) -> str:
        return self._news_view.toPlainText()

    def header_status_text(self) -> str:
        return self._header_status.text()

    def symbol_field(self) -> QLineEdit:
        return self._symbol_input

    def lookback_field(self) -> QSpinBox:
        return self._lookback_input

    def news_limit_field(self) -> QSpinBox:
        return self._news_limit_input

    def news_ticker(self) -> NewsTicker:
        return self._news_ticker

    def set_symbol_catalogue(self, symbols) -> None:
        """Replace the autocomplete dictionary used by the symbol input."""
        cleaned = sorted({str(s).strip().upper() for s in symbols if s})
        self._completer_model.setStringList(cleaned)

    def completer(self) -> QCompleter:
        return self._completer
