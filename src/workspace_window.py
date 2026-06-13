"""Controller wiring MainWindow to the validated MM.AI pipeline.

Supports comma-separated multi-symbol input. The pipeline runs on a
background ``QThread`` so the news HTTP fetch never blocks the UI thread.
A synchronous helper :func:`run_pipeline` is exposed for headless testing.
"""

from __future__ import annotations

from html import escape
from typing import Any, Iterable

from PySide6.QtCore import QObject, QThread, Signal, Slot
from PySide6.QtWidgets import QDialog

from datetime import datetime

from . import symbol_catalog
from .llm_models import TIMESTAMP_FORMAT
from .news_fetcher import DEFAULT_TIMEOUT_SECONDS, fetch_symbol_news
from .news_models import NewsResult
from .observation_builder import build_observations
from .observation_table import render_observation_html
from .symbol_extractor import extract_symbols_from_question
from .symbol_reader import load_symbol_data
from .talk_runner import TalkRunner
from .text_formatter import NA, format_observations
from .ui.main_window import MainWindow
from .ui.symbol_picker import SymbolPickerDialog
from .ui.theme import PALETTE, StatusState

NEWS_RULE = "-" * 50

_TEXT_PRIMARY = PALETTE["text_primary"]
_TEXT_SECONDARY = PALETTE["text_secondary"]
_ACCENT = PALETTE["accent"]
_BORDER = PALETTE["border"]
_HEADER_BG = PALETTE["header_bg"]


def parse_symbols(raw: str | None) -> list[str]:
    """Parse a free-text symbol field into deduplicated upper-case symbols.

    Accepts ``"RELIANCE"`` or ``"RELIANCE, INFY, NIFTY"`` (any whitespace).
    Empty fragments are dropped; order of first appearance is preserved.
    """
    if not raw:
        return []
    seen: dict[str, None] = {}
    for part in raw.replace(";", ",").split(","):
        sym = part.strip().upper()
        if sym and sym not in seen:
            seen[sym] = None
    return list(seen.keys())


def _build_observations_for_symbol(
    symbol: str, lookback: int
) -> tuple[dict[str, Any], str | None]:
    try:
        data = load_symbol_data(symbol, lookback_sessions=lookback)
        return build_observations(data), None
    except ValueError as exc:
        return _empty_observation(symbol, lookback), f"{exc}"
    except OSError as exc:
        return _empty_observation(symbol, lookback), f"I/O: {exc}"
    except Exception as exc:  # noqa: BLE001
        return _empty_observation(symbol, lookback), f"{type(exc).__name__}: {exc}"


def _empty_observation(symbol: str, lookback: int) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "lookback_sessions": lookback,
        "cash": {},
        "fo": {},
    }


def _section_style() -> str:
    return f"color: {_TEXT_SECONDARY};"


def _render_one_symbol_news(result: NewsResult) -> str:
    """Render one symbol's news block.

    The URL is *not* displayed — instead the headline text itself is the
    clickable anchor (with the URL surfaced as a tooltip via ``title=``).
    """
    section_style = _section_style()
    primary_style = f"color: {_TEXT_PRIMARY};"
    rule_style = f"color: {_BORDER};"
    headline_link_style = (
        f"color: {_TEXT_PRIMARY}; text-decoration: none;"
    )
    header_style = (
        f"color: {_ACCENT};"
        f"background-color: {_HEADER_BG};"
        f"padding: 4px 8px;"
        f"letter-spacing: 1px;"
    )

    parts: list[str] = []
    err_suffix = f" — ERROR: {escape(result.error)}" if result.error else ""
    parts.append(
        f'<p style="{header_style}">'
        f'═ {escape(result.symbol or NA)} &nbsp;[{escape(result.timestamp)}]'
        f' &nbsp;count: {result.count}{err_suffix} ═'
        f"</p>"
    )

    if not result.items:
        parts.append(
            f'<p style="{section_style}">Source:<br>{NA}</p>'
            f'<p style="{section_style}">Headline:<br>{NA}</p>'
            f'<p style="{rule_style}">{NEWS_RULE}</p>'
        )
        return "".join(parts)

    for item in result.items:
        headline_text = escape(item.headline) if item.headline else NA
        source = escape(item.source) if item.source else NA
        url_attr = escape(item.url, quote=True) if item.url else ""
        if item.url:
            headline_html = (
                f'<a href="{url_attr}" title="{url_attr}" '
                f'style="{headline_link_style}">{headline_text}</a>'
            )
        else:
            headline_html = headline_text
        parts.append(
            f'<p style="{section_style}">Source:<br>{source}</p>'
            f'<p style="{primary_style}">Headline:<br>{headline_html}</p>'
            f'<p style="{rule_style}">{NEWS_RULE}</p>'
        )
    return "".join(parts)


def _format_news_html(results: NewsResult | Iterable[NewsResult]) -> str:
    """Render a single NewsResult or an iterable of them into one HTML block."""
    if isinstance(results, NewsResult):
        result_list = [results]
    else:
        result_list = list(results)

    container_style = (
        f"font-family: Consolas, 'Cascadia Mono', monospace;"
        f"color: {_TEXT_PRIMARY};"
        f"white-space: pre-wrap;"
    )
    parts: list[str] = [f'<div style="{container_style}">']

    if not result_list:
        parts.append(
            f'<p style="{_section_style()}">No symbols loaded.</p>'
            f'<p style="color: {_BORDER};">{NEWS_RULE}</p>'
        )
        parts.append("</div>")
        return "".join(parts)

    for result in result_list:
        parts.append(_render_one_symbol_news(result))

    parts.append("</div>")
    return "".join(parts)


def run_pipeline(
    symbols: str | Iterable[str],
    *,
    lookback: int = 5,
    news_limit: int = 5,
    news_timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> tuple[str, str, list[NewsResult]]:
    """Synchronous pipeline runner used by both the UI worker and tests.

    ``symbols`` accepts a single string ("RELIANCE"), a comma-separated
    string ("RELIANCE, INFY, NIFTY"), or any iterable of strings. Returns
    ``(observation_html, news_html, news_results)``.
    """
    if isinstance(symbols, str):
        sym_list = parse_symbols(symbols)
    else:
        seen: dict[str, None] = {}
        for s in symbols:
            up = (s or "").strip().upper()
            if up and up not in seen:
                seen[up] = None
        sym_list = list(seen.keys())

    observations: list[dict[str, Any]] = []
    for sym in sym_list:
        obs, _err = _build_observations_for_symbol(sym, lookback)
        observations.append(obs)

    obs_html = render_observation_html(observations)

    news_results: list[NewsResult] = [
        fetch_symbol_news(sym, limit=news_limit, timeout=news_timeout)
        for sym in sym_list
    ]
    news_html = _format_news_html(news_results)
    return obs_html, news_html, news_results


class _PipelineWorker(QObject):
    """Background worker — owns the pipeline call inside its own thread."""

    finished = Signal(str, str, str, object, object)
    failed = Signal(str)

    def __init__(
        self,
        symbols: list[str],
        lookback: int,
        news_limit: int,
        news_timeout: float,
    ) -> None:
        super().__init__()
        self._symbols = symbols
        self._lookback = lookback
        self._news_limit = news_limit
        self._news_timeout = news_timeout

    @Slot()
    def run(self) -> None:
        try:
            obs_html, news_html, news_results = run_pipeline(
                self._symbols,
                lookback=self._lookback,
                news_limit=self._news_limit,
                news_timeout=self._news_timeout,
            )
            workspace_text = _workspace_text_for_symbols(
                self._symbols, self._lookback
            )
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(f"{type(exc).__name__}: {exc}")
            return
        total = sum(r.count for r in news_results)
        errors = [r.error for r in news_results if r.error]
        if errors:
            status = (
                f"loaded {len(self._symbols)} symbol(s) — news: {total} "
                f"({len(errors)} feed error{'s' if len(errors) > 1 else ''})"
            )
        else:
            status = f"loaded {len(self._symbols)} symbol(s) — news: {total}"
        self.finished.emit(
            obs_html, news_html, status, news_results, workspace_text
        )


def _workspace_text_for_symbols(symbols: list[str], lookback: int) -> str:
    """Produce the deterministic plain-text observation block for the LLM."""
    blocks: list[str] = []
    for sym in symbols:
        try:
            sd = load_symbol_data(sym, lookback_sessions=lookback)
            obs = build_observations(sd)
        except Exception as exc:  # noqa: BLE001
            blocks.append(
                f"SYMBOL: {sym}\n(observation unavailable: "
                f"{type(exc).__name__})\n"
            )
            continue
        blocks.append(format_observations(obs))
    return "\n\n".join(blocks)


class WorkspaceController(QObject):
    """Wires a ``MainWindow`` to background pipeline workers.

    Before the worker starts each token in the symbol input is checked
    against MM's existing catalogue. Unknown tokens trigger a modal
    :class:`SymbolPickerDialog` so the user can pick a near-match. Tokens
    where the user cancels are silently dropped.

    The controller also owns the :class:`TalkRunner` — every successful
    pipeline run pushes the deterministic workspace context into the
    runner so the Talk to Market panel always has fresh data to build a
    prompt against.
    """

    def __init__(
        self,
        window: MainWindow,
        *,
        talk_runner: TalkRunner | None = None,
    ) -> None:
        super().__init__(window)
        self._window = window
        self._thread: QThread | None = None
        self._worker: _PipelineWorker | None = None
        self._picker_factory = _default_picker_factory
        self._last_news_results: list[NewsResult] = []
        self._last_symbols: list[str] = []
        self._window.load_requested.connect(self._on_load_requested)
        try:
            self._window.set_symbol_catalogue(symbol_catalog.list_all_symbols())
        except Exception:  # noqa: BLE001
            # Catalogue is best-effort. Autocomplete simply stays empty if
            # MM's JSON cache files are absent on this machine.
            pass

        self._talk_runner = talk_runner if talk_runner is not None else TalkRunner(self)
        self._talk_widget = window.talk_widget()
        self._pending_talk_question: str | None = None
        self._wire_talk()

    # ---- Talk to Market wiring -----------------------------------------

    def _wire_talk(self) -> None:
        self._talk_widget.talk_requested.connect(self._on_talk_requested)
        self._talk_runner.started.connect(self._on_talk_started)
        self._talk_runner.finished_ok.connect(self._on_talk_finished_ok)
        self._talk_runner.finished_error.connect(self._on_talk_finished_error)

    @Slot(str)
    def _on_talk_requested(self, question: str) -> None:
        """Handle the Talk button.

        Flow:
        1. Empty question      -> delegate to TalkRunner (renders the
                                  "Enter a market question." error).
        2. Extract symbols from the question using MM's existing
           catalogue. If any symbols are mentioned that are NOT already
           loaded, auto-load the union (current ∪ mentioned) first and
           chain the ask once the workspace pipeline finishes.
        3. Otherwise (no symbols mentioned, or all already loaded), fire
           the ask immediately. TalkRunner handles the
           "no workspace loaded" fallback if the workspace is still empty.
        """
        q = (question or "").strip()
        if not q:
            self._talk_runner.ask(q)
            return

        self._window.set_status_state(StatusState.EXTRACTING_SYMBOLS)
        try:
            known = list(symbol_catalog.list_all_symbols())
        except Exception:  # noqa: BLE001
            known = []
        extracted = extract_symbols_from_question(
            q, known_symbols=known or None
        )

        current = list(self._last_symbols or [])
        current_set = set(current)
        new_in_question = [s for s in extracted if s not in current_set]

        if not new_in_question:
            # No new symbols mentioned, OR the question is purely
            # conversational. TalkRunner handles "no workspace" fallback.
            self._talk_runner.ask(q)
            return

        to_load = current + new_in_question  # preserves order, union
        lookback = self._window.lookback_field().value()
        news_limit = self._window.news_limit_field().value()
        self._pending_talk_question = q
        header = f"LOADING {', '.join(to_load)}..."
        self._start_pipeline(
            to_load,
            lookback,
            news_limit,
            header_override=header,
        )

    @Slot()
    def _on_talk_started(self) -> None:
        self._talk_widget.set_busy(True)
        self._window.set_status_state(StatusState.GENERATING)

    @Slot(str, str)
    def _on_talk_finished_ok(self, text: str, timestamp: str) -> None:
        # Distinguish the "no workspace loaded" fallback so the panel can
        # render it with a softer colour.
        from .talk_runner import NO_WORKSPACE_MESSAGE

        kind = "fallback" if text == NO_WORKSPACE_MESSAGE else "ok"
        self._talk_widget.set_response(text, timestamp, kind=kind)
        self._talk_widget.set_busy(False)
        if kind == "fallback":
            # Don't claim the response is ready when we just told the user
            # to load a workspace first.
            self._window.set_status_state(StatusState.READY)
        else:
            self._window.set_status_state(StatusState.RESPONSE_READY)

    @Slot(str, str)
    def _on_talk_finished_error(self, text: str, timestamp: str) -> None:
        self._talk_widget.set_response(text, timestamp, kind="error")
        self._talk_widget.set_busy(False)
        self._window.set_status_state(StatusState.RESPONSE_ERROR)

    # ---- public test hooks ---------------------------------------------

    def talk_runner(self) -> TalkRunner:
        return self._talk_runner

    def set_picker_factory(self, factory) -> None:
        """Inject a test double for the picker dialog.

        ``factory(query, candidates, parent) -> (chosen: str | None, accepted: bool)``
        """
        self._picker_factory = factory

    def resolve_symbols(self, raw_symbols: list[str]) -> list[str]:
        """Return ``raw_symbols`` with unknown tokens resolved via the picker.

        Known tokens pass through unchanged. Unknown tokens are presented in
        a modal picker; the user's selection replaces the token, or the
        token is dropped if the user cancels. Order and dedup are preserved.
        """
        try:
            known = set(symbol_catalog.list_all_symbols())
        except Exception:  # noqa: BLE001
            known = set()

        resolved: list[str] = []
        for token in raw_symbols:
            if token in known or not known:
                # When the catalogue is empty (MM cache missing) we trust
                # the user's input and let the parquet reader fail later
                # with a regular not-available observation.
                resolved.append(token)
                continue
            candidates = symbol_catalog.find_matches(token)
            chosen, accepted = self._picker_factory(token, candidates, self._window)
            if accepted and chosen:
                resolved.append(chosen.strip().upper())
            # cancelled -> token dropped

        # Preserve order, drop duplicates introduced by picker.
        seen: dict[str, None] = {}
        for s in resolved:
            if s and s not in seen:
                seen[s] = None
        return list(seen)

    @Slot(str, int, int)
    def _on_load_requested(self, raw_symbol: str, lookback: int, news_limit: int) -> None:
        parsed = parse_symbols(raw_symbol)
        if not parsed:
            self._window.set_status("error: enter at least one symbol")
            return
        if lookback < 1:
            self._window.set_status("error: lookback must be >= 1")
            return
        if news_limit < 1:
            self._window.set_status("error: news limit must be >= 1")
            return

        symbols = self.resolve_symbols(parsed)
        if not symbols:
            self._window.set_status(
                "error: no valid symbols selected (all unknown or cancelled)"
            )
            return

        if symbols != parsed:
            self._window.symbol_field().setText(", ".join(symbols))

        self._start_pipeline(symbols, lookback, news_limit)

    def _start_pipeline(
        self,
        symbols: list[str],
        lookback: int,
        news_limit: int,
        *,
        header_override: str | None = None,
    ) -> None:
        """Spawn the workspace pipeline worker for ``symbols``.

        Shared between the symbol bar (Enter / picker resolution) and the
        Talk to Market auto-load chain. The optional ``header_override``
        lets the Talk path render the literal
        ``"LOADING NIFTY, RELIANCE..."`` token the spec asks for.
        """
        self._last_symbols = list(symbols)
        self._window.set_load_enabled(False)
        self._window.symbol_field().setText(", ".join(symbols))
        if header_override is not None:
            self._window.set_status_state(
                StatusState.LOADING_SYMBOL,
                header_override=header_override,
            )
        elif len(symbols) == 1:
            self._window.set_status_state(
                StatusState.LOADING_SYMBOL, symbols[0]
            )
        else:
            self._window.set_status_state(
                StatusState.LOADING_SYMBOL, ", ".join(symbols)
            )

        thread = QThread()
        worker = _PipelineWorker(
            symbols, lookback, news_limit, DEFAULT_TIMEOUT_SECONDS
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._on_finished)
        worker.failed.connect(self._on_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._clear_refs)
        self._thread = thread
        self._worker = worker
        thread.start()

    @Slot(str, str, str, object, object)
    def _on_finished(
        self,
        observation_html: str,
        news_html: str,
        status: str,
        news_results: list,
        workspace_text: str,
    ) -> None:
        self._window.set_observation_html(observation_html)
        self._window.set_news_html(news_html)
        self._window.set_status_state(StatusState.WORKSPACE_READY, status)
        self._window.set_load_enabled(True)
        self._last_news_results = list(news_results or [])
        self._talk_runner.set_workspace(
            workspace_text=workspace_text,
            workspace_html=observation_html,
            news_items=self._last_news_results,
            symbols=self._last_symbols,
        )
        # Chain into the deferred Talk call if this load was kicked off
        # by the Talk auto-load path.
        pending = self._pending_talk_question
        if pending:
            self._pending_talk_question = None
            self._talk_runner.ask(pending)

    @Slot(str)
    def _on_failed(self, message: str) -> None:
        self._window.set_status_state(StatusState.WORKSPACE_ERROR, message)
        self._window.set_load_enabled(True)
        # If Talk was waiting for this load, surface the failure in the
        # response panel instead of leaving the user stranded.
        pending = self._pending_talk_question
        if pending:
            self._pending_talk_question = None
            ts = datetime.now().strftime(TIMESTAMP_FORMAT)
            self._talk_widget.set_response(
                f"workspace_error: {message}", ts, kind="error"
            )
            self._window.set_status_state(StatusState.RESPONSE_ERROR)

    @Slot()
    def _clear_refs(self) -> None:
        self._thread = None
        self._worker = None


def _default_picker_factory(
    query: str, candidates, parent
) -> tuple[str | None, bool]:
    """Real picker used in production. Tests inject a substitute."""
    dialog = SymbolPickerDialog(query, candidates, parent=parent)
    result = dialog.exec()
    if result == QDialog.DialogCode.Accepted:
        return dialog.selected_symbol(), True
    return None, False


def create_workspace_window() -> tuple[MainWindow, WorkspaceController]:
    window = MainWindow()
    controller = WorkspaceController(window)
    return window, controller
