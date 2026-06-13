"""Dark institutional terminal theme for the MM.AI desktop UI.

UX Step 1 — base visual styling only. Layout, signals, and the backend
pipeline are not touched. The palette is applied via one global QSS string
plus an application-level UI font; data views additionally use a monospace
font for tabular legibility.
"""

from __future__ import annotations

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

PALETTE = {
    "window_bg": "#0B0F14",
    "header_bg": "#050A12",
    "panel_bg": "#111827",
    "input_bg": "#0F172A",
    "border": "#243244",
    "border_focus": "#3B82F6",
    "text_primary": "#E5E7EB",
    "text_secondary": "#9CA3AF",
    "text_disabled": "#6B7280",
    "accent": "#3B82F6",
    "accent_hover": "#2563EB",
    "warn": "#E0A86C",
    "error": "#E06C75",
    "success": "#9CE3A8",
    "scrollbar_track": "#0B0F14",
    "scrollbar_thumb": "#243244",
    "scrollbar_thumb_hover": "#2F4360",
}


# Status-bar state tokens. Use these constants from the controllers — they
# are mapped to subtle colours via QSS dynamic-property selectors below.
class StatusState:
    READY = "READY"
    EXTRACTING_SYMBOLS = "EXTRACTING SYMBOLS..."
    LOADING_SYMBOL = "LOADING SYMBOL..."
    WORKSPACE_READY = "WORKSPACE READY"
    WORKSPACE_ERROR = "WORKSPACE ERROR"
    GENERATING = "GENERATING MARKET RESPONSE..."
    RESPONSE_READY = "MARKET RESPONSE READY"
    RESPONSE_ERROR = "MARKET RESPONSE ERROR"


# Map state token -> QSS dynamic property value ("kind") -> colour.
STATUS_KIND_FOR_STATE: dict[str, str] = {
    StatusState.READY: "idle",
    StatusState.EXTRACTING_SYMBOLS: "busy",
    StatusState.LOADING_SYMBOL: "busy",
    StatusState.WORKSPACE_READY: "ok",
    StatusState.WORKSPACE_ERROR: "error",
    StatusState.GENERATING: "busy",
    StatusState.RESPONSE_READY: "ok",
    StatusState.RESPONSE_ERROR: "error",
}

UI_FONT_FAMILY = "Segoe UI"
UI_FONT_SIZE = 9
MONO_FONT_FAMILY = "Consolas"
MONO_FONT_SIZE = 10
TITLE_FONT_SIZE = 12

QSS_TEMPLATE = """
QMainWindow {{
    background-color: {window_bg};
    color: {text_primary};
}}

QWidget {{
    background-color: {window_bg};
    color: {text_primary};
}}

QToolTip {{
    background-color: {panel_bg};
    color: {text_primary};
    border: 1px solid {border};
}}

QWidget#HeaderBar {{
    background-color: {header_bg};
    border-bottom: 1px solid {border};
}}

QLabel#HeaderTitle {{
    color: {text_primary};
    font-family: "{ui_font}";
    font-size: {title_size}pt;
    font-weight: 700;
    letter-spacing: 1px;
}}

QLabel#HeaderClock,
QLabel#HeaderStatus {{
    color: {text_secondary};
    font-family: "{mono_font}";
    font-size: {ui_size}pt;
    letter-spacing: 1px;
}}

QLabel#HeaderStatus[kind="busy"] {{
    color: {accent};
}}

QLabel#HeaderStatus[kind="ok"] {{
    color: {success};
}}

QLabel#HeaderStatus[kind="error"] {{
    color: {error};
}}

QStatusBar[kind="busy"] {{
    color: {accent};
}}

QStatusBar[kind="ok"] {{
    color: {success};
}}

QStatusBar[kind="error"] {{
    color: {error};
}}

QLabel#SectionLabel {{
    color: {text_secondary};
    font-family: "{ui_font}";
    font-size: {ui_size}pt;
    font-weight: 700;
    letter-spacing: 2px;
    padding-top: 2px;
    padding-bottom: 2px;
}}

QLabel#FieldLabel {{
    color: {text_secondary};
    font-family: "{ui_font}";
    font-size: {ui_size}pt;
}}

QLineEdit,
QSpinBox {{
    background-color: {input_bg};
    color: {text_primary};
    border: 1px solid {border};
    border-radius: 2px;
    padding: 5px 8px;
    selection-background-color: {accent};
    selection-color: #FFFFFF;
    font-family: "{mono_font}";
    font-size: {ui_size}pt;
}}

QLineEdit:focus,
QSpinBox:focus {{
    border-color: {border_focus};
}}

QLineEdit:disabled,
QSpinBox:disabled {{
    color: {text_disabled};
    border-color: #1F2937;
}}

QSpinBox::up-button,
QSpinBox::down-button {{
    width: 0px;
    height: 0px;
    border: none;
    background: transparent;
}}

QSpinBox#LookbackInput,
QSpinBox#NewsLimitInput {{
    padding: 5px 4px;
    qproperty-alignment: AlignCenter;
}}

QPushButton {{
    background-color: {panel_bg};
    color: {text_primary};
    border: 1px solid {border};
    border-radius: 2px;
    padding: 6px 16px;
    font-family: "{ui_font}";
    font-size: {ui_size}pt;
    font-weight: 600;
    letter-spacing: 1px;
}}

QPushButton:hover {{
    background-color: #1F2937;
    border-color: {border_focus};
}}

QPushButton:pressed {{
    background-color: {input_bg};
}}

QPushButton:default {{
    border: 1px solid {accent};
}}

QPushButton:default:hover {{
    background-color: {accent};
    color: #FFFFFF;
}}

QPushButton:disabled {{
    color: {text_disabled};
    border-color: #1F2937;
    background-color: {panel_bg};
}}

QPlainTextEdit,
QTextBrowser {{
    background-color: {panel_bg};
    color: {text_primary};
    border: 1px solid {border};
    selection-background-color: {accent};
    selection-color: #FFFFFF;
    font-family: "{mono_font}";
    font-size: {mono_size}pt;
}}

QPlainTextEdit:focus,
QTextBrowser:focus {{
    border-color: {border_focus};
}}

QStatusBar {{
    background-color: {header_bg};
    color: {text_secondary};
    border-top: 1px solid {border};
    font-family: "{mono_font}";
    font-size: {ui_size}pt;
}}

QStatusBar::item {{
    border: none;
}}

QSplitter::handle {{
    background-color: {header_bg};
}}

QSplitter::handle:vertical {{
    height: 4px;
}}

QScrollBar:vertical {{
    background: {scrollbar_track};
    width: 12px;
    margin: 0;
    border: none;
}}

QScrollBar::handle:vertical {{
    background: {scrollbar_thumb};
    min-height: 24px;
    border-radius: 2px;
}}

QScrollBar::handle:vertical:hover {{
    background: {scrollbar_thumb_hover};
}}

QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {{
    height: 0;
    background: transparent;
}}

QScrollBar::add-page:vertical,
QScrollBar::sub-page:vertical {{
    background: transparent;
}}

QScrollBar:horizontal {{
    background: {scrollbar_track};
    height: 12px;
    margin: 0;
    border: none;
}}

QScrollBar::handle:horizontal {{
    background: {scrollbar_thumb};
    min-width: 24px;
    border-radius: 2px;
}}

QScrollBar::handle:horizontal:hover {{
    background: {scrollbar_thumb_hover};
}}

QScrollBar::add-line:horizontal,
QScrollBar::sub-line:horizontal {{
    width: 0;
    background: transparent;
}}

/* ----- Talk to Market section ----- */

QWidget#TalkHolder {{
    background-color: {window_bg};
}}

QLabel#TalkExamples {{
    color: {text_disabled};
    font-family: "{ui_font}";
    font-size: {ui_size}pt;
    padding: 0 2px;
}}

QLabel#TalkResponseHeader {{
    color: {text_secondary};
    font-family: "{ui_font}";
    font-size: {ui_size}pt;
    font-weight: 700;
    letter-spacing: 2px;
}}

QLabel#TalkResponseTimestamp {{
    color: {text_disabled};
    font-family: "{mono_font}";
    font-size: {ui_size}pt;
}}

QPlainTextEdit#TalkQuestionInput {{
    background-color: {input_bg};
    color: {text_primary};
    border: 1px solid {border};
    border-radius: 2px;
    padding: 6px 8px;
    font-family: "{mono_font}";
    font-size: {mono_size}pt;
    line-height: 140%;
    selection-background-color: {accent};
    selection-color: #FFFFFF;
}}

QPlainTextEdit#TalkQuestionInput:focus {{
    border-color: {border_focus};
}}

QPlainTextEdit#TalkResponseView {{
    background-color: #0A0F18;
    color: {text_primary};
    border: 1px solid {border};
    border-radius: 2px;
    padding: 8px 10px;
    font-family: "{mono_font}";
    font-size: {mono_size}pt;
    line-height: 150%;
    selection-background-color: {accent};
    selection-color: #FFFFFF;
}}

QPlainTextEdit#TalkResponseView[kind="error"] {{
    color: {error};
}}

QPlainTextEdit#TalkResponseView[kind="fallback"] {{
    color: {text_secondary};
}}

QPushButton#TalkButton {{
    background-color: {panel_bg};
    color: {text_primary};
    border: 1px solid {accent};
    border-radius: 2px;
    padding: 6px 22px;
    font-family: "{ui_font}";
    font-size: {ui_size}pt;
    font-weight: 700;
    letter-spacing: 2px;
}}

QPushButton#TalkButton:hover {{
    background-color: {accent};
    color: #FFFFFF;
}}

QPushButton#TalkButton:disabled {{
    color: {text_disabled};
    border-color: #1F2937;
}}

QPushButton#TalkSmallButton {{
    background-color: transparent;
    color: {text_secondary};
    border: 1px solid {border};
    border-radius: 2px;
    padding: 2px 10px;
    font-family: "{ui_font}";
    font-size: {ui_size}pt;
    font-weight: 600;
    letter-spacing: 1px;
}}

QPushButton#TalkSmallButton:hover {{
    color: {text_primary};
    border-color: {border_focus};
}}

QPushButton#TalkSmallButton:disabled {{
    color: {text_disabled};
    border-color: #1F2937;
}}
"""


def build_qss() -> str:
    return QSS_TEMPLATE.format(
        window_bg=PALETTE["window_bg"],
        header_bg=PALETTE["header_bg"],
        panel_bg=PALETTE["panel_bg"],
        input_bg=PALETTE["input_bg"],
        border=PALETTE["border"],
        border_focus=PALETTE["border_focus"],
        text_primary=PALETTE["text_primary"],
        text_secondary=PALETTE["text_secondary"],
        text_disabled=PALETTE["text_disabled"],
        accent=PALETTE["accent"],
        accent_hover=PALETTE["accent_hover"],
        success=PALETTE["success"],
        error=PALETTE["error"],
        warn=PALETTE["warn"],
        scrollbar_track=PALETTE["scrollbar_track"],
        scrollbar_thumb=PALETTE["scrollbar_thumb"],
        scrollbar_thumb_hover=PALETTE["scrollbar_thumb_hover"],
        ui_font=UI_FONT_FAMILY,
        ui_size=UI_FONT_SIZE,
        mono_font=MONO_FONT_FAMILY,
        mono_size=MONO_FONT_SIZE,
        title_size=TITLE_FONT_SIZE,
    )


def apply_theme(app: QApplication) -> None:
    """Apply the MM.AI dark institutional terminal theme to a QApplication."""
    app.setFont(QFont(UI_FONT_FAMILY, UI_FONT_SIZE))
    app.setStyleSheet(build_qss())


def mono_font() -> QFont:
    return QFont(MONO_FONT_FAMILY, MONO_FONT_SIZE)
