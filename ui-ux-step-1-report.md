# MM.AI Desktop UI — UX Step 1 Report

Step: **Base dark institutional theme (Bloomberg-style terminal look).**
Layout structure, signals, controllers, and the backend pipeline are unchanged.

---

## 1. Files Modified / Added (inside `MM.AI/`)

| File | Change |
| --- | --- |
| `src/ui/theme.py` | **New.** Holds the palette, font names, the QSS template, `build_qss()`, `apply_theme(app)`, and `mono_font()`. |
| `src/ui/main_window.py` | Removed light-mode inline stylesheets and the hard-coded `QFont("Consolas", 10)` constant; assigned `objectName`s (`HeaderBar`, `HeaderTitle`, `HeaderClock`, `HeaderStatus`, `SectionLabel`, `FieldLabel`, `SymbolInput`, `LookbackInput`, `NewsLimitInput`, `LoadWorkspaceButton`, `ObservationView`, `NewsView`, `WorkspaceStatusBar`, `ContentSplitter`, `ObservationHolder`, `NewsHolder`, `SearchBar`, `WorkspaceRoot`, `MMWorkspaceWindow`); enabled `WA_StyledBackground` on the header so QSS background paints. Data views now pick up the mono font from `theme.mono_font()`. **Layout, sizes, widget tree, and label texts are unchanged.** |
| `src/app.py` | Calls `apply_theme(app)` after `QApplication` creation, before showing the window. |
| `src/workspace_window.py` | `_format_news_html` now emits inline styles (color/spacing) that pull from `theme.PALETTE` so `QTextBrowser` renders against the dark base: section copy in `#9CA3AF`, primary headline in `#E5E7EB`, clickable URLs in accent `#3B82F6`, rule dashes in `#243244`. No structural change — same number of anchors, same item separator, same `Source/Headline/URL` order. |
| `tests/_ui_theme_validation_run.py` | **New helper** (underscore-prefixed, not collected by pytest). Boots a real `QApplication`, applies the theme, runs the pipeline for the three required symbols, and prints a JSON validation summary. |

No other file was touched. MM core, parquet, and the backend pipeline (`symbol_reader`, `observation_builder`, `text_formatter`, `news_fetcher`) are byte-identical.

---

## 2. Styling Applied

### 2.1 Palette (verified verbatim against `theme.PALETTE`)

| Token | Value | Used For |
| --- | --- | --- |
| `window_bg` | `#0B0F14` | `QMainWindow`, root `QWidget`, scroll-bar track. |
| `header_bg` | `#050A12` | `HeaderBar`, `QStatusBar`, splitter handle. |
| `panel_bg` | `#111827` | `QPlainTextEdit`, `QTextBrowser`, `QPushButton`, `QSpinBox` step buttons. |
| `input_bg` | `#0F172A` | `QLineEdit`, `QSpinBox` text area. |
| `border` | `#243244` | Subtle borders on inputs, panels, status bar, scroll-bar thumb. |
| `border_focus` / `accent` | `#3B82F6` | Focus rings, default-button border, accent hover, news anchor colour. |
| `text_primary` | `#E5E7EB` | Primary text in observation panel, headline text in news panel, button labels. |
| `text_secondary` | `#9CA3AF` | Header clock, header status, section labels (`OBSERVATIONS`, `NEWS`), field labels, status bar copy, news `Source:` / `URL:` / `SYMBOL:` / `COUNT:` lines. |
| `text_disabled` | `#6B7280` | Disabled inputs/buttons. |
| `scrollbar_thumb_hover` | `#2F4360` | Scroll-bar thumb hover state. |

No gradients. No saturated colours. Single neutral grey/navy base + single blue accent. Border thickness is 1 px throughout; corner radius is 2 px (subtle, terminal-flat).

### 2.2 Fonts

| Surface | Family | Size |
| --- | --- | --- |
| Application default (labels, buttons, status bar) | **Segoe UI** | 9 pt |
| Header title (`MM.AI Workspace`) | Segoe UI, weight 700, +1 px letter-spacing | 14 pt |
| Header clock / header status / status bar | **Consolas** | 9 pt |
| `QLineEdit`, `QSpinBox` (so symbols/numbers align with terminal feel) | **Consolas** | 9 pt |
| Observation panel (`QPlainTextEdit`) | **Consolas** | 10 pt |
| News panel (`QTextBrowser`) | **Consolas** | 10 pt |
| Section labels (`OBSERVATIONS`, `NEWS`) | Segoe UI, weight 700, +2 px letter-spacing | 9 pt |

QSS declares `font-family: "Consolas"` with `'Cascadia Mono', monospace` as the HTML-level fallback inside the news `QTextBrowser`. UI font has implicit Qt sans-serif fallback.

### 2.3 Interaction States

- `QLineEdit:focus`, `QSpinBox:focus`, `QPlainTextEdit:focus`, `QTextBrowser:focus` → border swaps from `#243244` to `#3B82F6`.
- `QPushButton` default state border is `#3B82F6` (the `Load Workspace` button is the QDialog default); hover fills the button in accent `#3B82F6` with white text; pressed dims to `#0F172A`; disabled greys to `#6B7280` over `#111827`.
- Scroll bars are 12 px wide, hidden up/down arrows, rounded 2 px thumb that brightens on hover.
- Splitter handle is 4 px, painted in `header_bg` for a faint divider between the two stacked sections.
- Selection (text highlight) is `#3B82F6` background with white text in every editable / read-only text widget.

### 2.4 Confirmation of "no layout change"

The widget tree, layout margins (12 px outer, 0 px inner), spacings (10 px between rows, 8 px in the search bar), section ordering, fixed header height (60 px), splitter sizes (`[420, 340]`), and every label/placeholder/button text are identical to UX Step 0. Theme is the only change.

---

## 3. Symbols Tested

`RELIANCE`, `INFY`, `NIFTY`.

Validation harness: `tests/_ui_theme_validation_run.py` — boots `QApplication`, applies the theme (`apply_theme(app)`), shows a real `MainWindow`, then drives the pipeline (`run_pipeline`) and pushes the output into the live `QPlainTextEdit` / `QTextBrowser`.

### 3.1 QSS Sanity

```
qss_length            : 3590 chars
contains #0B0F14      : true   (window_bg)
contains #050A12      : true   (header_bg)
contains #111827      : true   (panel_bg)
contains #0F172A      : true   (input_bg)
contains #243244      : true   (border)
contains #E5E7EB      : true   (text_primary)
contains #9CA3AF      : true   (text_secondary)
contains #3B82F6      : true   (accent)
application.font()    : Segoe UI, 9pt
```

All eight palette tokens from the spec are present in the compiled QSS, the application font is Segoe UI 9 pt, and no legacy light-mode style remains in `main_window.py` (verified by inspection — every previous `setStyleSheet("background: #fafafa …")` and grey-on-white label override is gone).

---

## 4. Observation Rendering Validation (themed UI, live MM parquet)

`MM_INSTALL_ROOT = C:\Users\DELL\MMMarket`, lookback = 5.

| Symbol | obs chars | `SYMBOL:` line | CASH header | F&O header | Latest Session (cash) | Latest Close | Close Δ | Latest OI Total | Observation view font |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| RELIANCE | 813 | OK | OK | OK | `2026-05-20` | `1359.7` | `37.0` | `118900500.0` | Consolas |
| INFY | 809 | OK | OK | OK | `2026-05-20` | `1193.7` | `-3.2` (rounded artefact) | `67244000.0` | Consolas |
| NIFTY | 863 | OK | OK | OK | `Not Available` (cash absent) | `Not Available` | `Not Available` | `396523885.0` | Consolas |

- All three symbols routed through the themed widgets without exception.
- Plain-text content in the observation panel is **byte-identical** to UX Step 0 output (compared via `MainWindow.observation_text()`). Theme only re-painted; it did not reflow, re-pad, or re-format.
- `Not Available` placeholders for missing cash data on `NIFTY` render in primary text colour against the dark panel — fully legible.

---

## 5. News Rendering Validation (themed UI, live RSS)

| Symbol | News count | Anchors in HTML | HTML contains `#3B82F6` (anchor accent) | HTML contains `#E5E7EB` (primary text) | `news_error` |
| --- | --- | --- | --- | --- | --- |
| RELIANCE | 5 | 5 | OK | OK | None |
| INFY | 5 | 5 | OK | OK | None |
| NIFTY | 5 | 5 | OK | OK | None |

- Each news item still renders as four blocks (`Source` / `Headline` / `URL` / 50-dash rule) — same structure as UX Step 0, same separator characters, same ordering.
- URLs remain clickable (`<a href="…" style="color:#3B82F6; text-decoration:none">…</a>`) and `QTextBrowser.openExternalLinks` is still enabled.
- Headline strings carrying non-ASCII glyphs (e.g. `₹` in INFY headlines) render correctly inside `QTextBrowser` — no encoding fallback triggered.
- News HTML is HTML-escaped exactly as before (`test_news_html_escapes_unsafe_characters` continues to pass with the dark theme applied).

---

## 6. Regression / Test Results

```
pytest MM.AI/tests -q          →  57 passed
python tests/_ui_theme_validation_run.py  →  exit 0
                              (RELIANCE / INFY / NIFTY all rendered through a themed QApplication)
ReadLints (theme.py, main_window.py, app.py, workspace_window.py)  →  no errors
```

Existing tests (`test_window_defaults_and_size`, `test_news_html_contains_clickable_anchor_per_item`, `test_news_html_empty_renders_not_available`, `test_news_html_escapes_unsafe_characters`, controller guards, etc.) all pass without modification — proving the theme change is non-structural.

---

## 7. Warnings / Errors

- **None during themed runs** for RELIANCE, INFY, or NIFTY.
- The dark theme is applied via a single `QApplication.setStyleSheet` call; nested widgets do not need to re-paint manually. The `QTextBrowser` cannot pull `color` from the QSS for HTML content, so the inline styles in `_format_news_html` carry colour through into the rendered HTML. This is documented behaviour of Qt's rich-text engine — not a workaround for a bug.
- If the host machine lacks `Segoe UI` or `Consolas`, Qt automatically falls back to its default sans-serif / monospace families; layout proportions stay the same (widths/heights are pixel-driven, not glyph-driven).
- No deprecation warnings, no stylesheet parse warnings, no Qt platform plug-in warnings observed during the themed validation runs.
