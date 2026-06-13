"""Controller for the Talk to Market panel.

Owns the *latest* loaded workspace context (deterministic observation text,
HTML, news items, symbols) and translates a user question into a safe
prompt payload + local-LLM call.

The pipeline is **strictly**:

    user_question
        --> build_llm_prompt(...)            (safe prompt builder)
        --> generate_llm_response(payload)   (local LLM adapter)
        --> response_text (verbatim, plain)

No interpretation, no recommendation, no prediction is performed here.
The runner also enforces the deterministic UX fallbacks specified in the
spec:

- empty question        -> "Enter a market question."
- no workspace loaded   -> "No workspace loaded. Enter a symbol or ask
                            about a symbol directly."
- LLM error / timeout   -> error message surfaced unchanged through the
                           response panel with kind="error".

For testability the runner exposes both an async :meth:`ask` (used by the
UI; spawns a ``QThread``) and a synchronous :meth:`ask_sync` (used by
unit tests; same code path minus threading).
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Callable, Iterable

from PySide6.QtCore import QObject, QThread, Signal, Slot

from .llm_adapter import generate_llm_response
from .llm_config import LLMConfig, load_config_from_env
from .llm_models import TIMESTAMP_FORMAT
from .llm_prompt_builder import build_llm_prompt
from .llm_response_models import LLMResponse
from .news_models import NewsItem, NewsResult

EMPTY_QUESTION_MESSAGE = "Enter a market question."
NO_WORKSPACE_MESSAGE = (
    "No workspace loaded. Enter a symbol or ask about a symbol directly."
)
DEFAULT_ERROR_MESSAGE = "Market response unavailable."

# User-facing error strings for the response panel. The adapter still
# emits machine-readable tokens (``http_error: 404 Not Found``,
# ``timeout``, ``connection_failure: ...``) — we translate them here so
# the panel reads like an institutional terminal rather than a stack
# trace. Backend-specific wording is selected from ``response.backend``.
_TIMEOUT_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")


def _extract_timeout_seconds(error: str) -> str | None:
    """Return the integer seconds embedded in a ``timeout: <N>`` token.

    Accepts both ``timeout: 120`` and ``timeout: 60.0s``; returns the
    number stripped of any trailing unit. Returns ``None`` when the
    token does not carry a duration so the caller can fall back to the
    generic timed-out message.
    """
    if ":" not in error:
        return None
    suffix = error.split(":", 1)[1].strip()
    if not suffix:
        return None
    match = _TIMEOUT_NUMBER_RE.match(suffix)
    if not match:
        return None
    raw = match.group(0)
    # Render whole numbers without a trailing ``.0`` so the panel reads
    # "120 seconds" rather than "120.0 seconds".
    try:
        value = float(raw)
    except ValueError:
        return raw
    if value <= 0:
        return None
    if float(int(value)) == value:
        return str(int(value))
    return raw


def _runtime_label(backend: str) -> str:
    if backend == "ollama":
        return "Ollama"
    if backend == "openai_compatible":
        return "local LLM"
    return "local LLM runtime"


def _friendly_error_text(response: LLMResponse) -> str:
    """Translate an adapter error token into a user-facing message.

    The original ``response.error`` is preserved unchanged on the
    :class:`LLMResponse`; only the string handed to the UI is rewritten.
    """
    err = (response.error or "").strip()
    backend = (response.backend or "").strip().lower()
    label = _runtime_label(backend)

    if not err:
        return DEFAULT_ERROR_MESSAGE

    # Timeout — covers ``timeout`` (exact) and any ``timeout: <N>`` variant.
    # When the adapter embeds the configured duration we surface it to the
    # user so they can decide whether to raise MM_AI_LLM_TIMEOUT_SECONDS.
    if err == "timeout" or err.startswith("timeout"):
        seconds = _extract_timeout_seconds(err)
        if seconds is not None:
            return f"Local model request timed out after {seconds} seconds."
        return "Local model request timed out."

    # Connection layer (refused, name-resolution, network unreachable).
    if err.startswith("connection_failure") or err.startswith("resolve_failure"):
        return f"Unable to connect to local {label} runtime."

    # HTTP errors from the local runtime. Spec wording for 404 is exact.
    if err.startswith("http_error: 404"):
        if backend == "ollama":
            return "Ollama endpoint returned 404."
        return "Local model endpoint returned 404."
    if err.startswith("http_error: 5"):
        return f"Local {label} runtime reported a server error."
    if err.startswith("http_error: "):
        # Strip prefix; show only the human-readable HTTP status text.
        return f"Local {label} runtime returned an HTTP error."

    # Adapter-layer guards.
    if err.startswith("endpoint_rejected"):
        return (
            "Local LLM endpoint rejected: configure MM_AI_LLM_ENDPOINT to a "
            "loopback or private address."
        )
    if err.startswith("config_error"):
        return "Local LLM configuration error."
    if err.startswith("invalid_payload"):
        return "Local LLM request rejected (invalid payload)."
    if err.startswith("unsupported_backend"):
        return "Local LLM backend not supported."

    # Malformed / unexpected responses from the runtime.
    if err.startswith("malformed_response") or err.startswith("invalid_json"):
        return f"Local {label} runtime returned an unreadable response."

    # Catch-all — keep it short and factual; never expose tracebacks.
    return DEFAULT_ERROR_MESSAGE


def _now_timestamp() -> str:
    return datetime.now().strftime(TIMESTAMP_FORMAT)


class _LLMWorker(QObject):
    """Background worker — calls the adapter inside its own thread."""

    finished = Signal(object)

    def __init__(
        self,
        payload,
        config: LLMConfig | None,
        transport: Callable | None,
    ) -> None:
        super().__init__()
        self._payload = payload
        self._config = config
        self._transport = transport

    @Slot()
    def run(self) -> None:
        response = generate_llm_response(
            self._payload, self._config, transport=self._transport
        )
        self.finished.emit(response)


class TalkRunner(QObject):
    """Controller for the Talk to Market panel.

    Emits:
        ``started()``                     before a real LLM call.
        ``finished_ok(text, timestamp)``  on success / fallback message.
        ``finished_error(text, ts)``      on adapter failure or rejection.
    """

    started = Signal()
    finished_ok = Signal(str, str)
    finished_error = Signal(str, str)

    def __init__(
        self,
        parent: QObject | None = None,
        *,
        config: LLMConfig | None = None,
        transport: Callable | None = None,
    ) -> None:
        super().__init__(parent)
        self._workspace_text: str = ""
        self._workspace_html: str = ""
        self._news_items: list[NewsItem | NewsResult | dict] = []
        self._symbols: list[str] = []
        self._llm_config = config
        self._transport = transport
        self._thread: QThread | None = None
        self._worker: _LLMWorker | None = None

    # ---- workspace context ---------------------------------------------

    def set_workspace(
        self,
        workspace_text: str | None,
        workspace_html: str | None,
        news_items: Iterable[Any] | None,
        symbols: Iterable[str] | None,
    ) -> None:
        """Replace the deterministic context handed to the next call."""
        self._workspace_text = workspace_text or ""
        self._workspace_html = workspace_html or ""
        self._news_items = list(news_items or [])
        self._symbols = [str(s).strip().upper() for s in (symbols or []) if s]

    def clear_workspace(self) -> None:
        self._workspace_text = ""
        self._workspace_html = ""
        self._news_items = []
        self._symbols = []

    def has_workspace(self) -> bool:
        """True iff there is at least some observable context loaded."""
        return bool(self._workspace_text.strip()) or bool(self._symbols)

    def workspace_text(self) -> str:
        return self._workspace_text

    def workspace_symbols(self) -> tuple[str, ...]:
        return tuple(self._symbols)

    # ---- LLM call -------------------------------------------------------

    def _resolve_config(self) -> tuple[LLMConfig | None, str | None]:
        if self._llm_config is not None:
            return self._llm_config, None
        try:
            return load_config_from_env(), None
        except Exception as exc:  # noqa: BLE001
            return None, f"config_error: {exc}"

    def _build_payload(self, question: str):
        return build_llm_prompt(
            user_question=question,
            workspace_html=self._workspace_html or None,
            workspace_text=self._workspace_text or None,
            news_items=self._news_items,
            symbols=self._symbols,
        )

    def ask_sync(self, question: str | None) -> tuple[str, str, str]:
        """Synchronous handler used by tests.

        Returns ``(kind, text, timestamp)`` where ``kind`` is one of
        ``"ok"``, ``"error"``, ``"fallback"``.
        """
        ts = _now_timestamp()
        q = (question or "").strip()
        if not q:
            return "error", EMPTY_QUESTION_MESSAGE, ts
        if not self.has_workspace():
            return "fallback", NO_WORKSPACE_MESSAGE, ts

        config, config_err = self._resolve_config()
        if config is None or config_err:
            return "error", config_err or "config_error: unknown", ts

        try:
            payload = self._build_payload(q)
        except ValueError as exc:
            return "error", f"prompt_rejected: {exc}", _now_timestamp()
        except Exception as exc:  # noqa: BLE001
            return "error", f"prompt_error: {type(exc).__name__}: {exc}", _now_timestamp()

        response: LLMResponse = generate_llm_response(
            payload, config, transport=self._transport
        )
        ts = _now_timestamp()
        if response.ok:
            text = response.response_text or "(empty response)"
            return "ok", text, ts
        return "error", _friendly_error_text(response), ts

    @Slot(str)
    def ask(self, question: str | None) -> None:
        """Async handler used by the UI.

        For empty-question and no-workspace cases the result is emitted
        synchronously (no thread spawned). For real LLM calls the work is
        moved to a ``QThread`` so the UI stays responsive while the local
        model generates.
        """
        ts = _now_timestamp()
        q = (question or "").strip()
        if not q:
            self.finished_error.emit(EMPTY_QUESTION_MESSAGE, ts)
            return
        if not self.has_workspace():
            self.finished_ok.emit(NO_WORKSPACE_MESSAGE, ts)
            return

        config, config_err = self._resolve_config()
        if config is None or config_err:
            self.finished_error.emit(
                config_err or "config_error: unknown", ts
            )
            return

        try:
            payload = self._build_payload(q)
        except ValueError as exc:
            self.finished_error.emit(
                f"prompt_rejected: {exc}", _now_timestamp()
            )
            return
        except Exception as exc:  # noqa: BLE001
            self.finished_error.emit(
                f"prompt_error: {type(exc).__name__}: {exc}",
                _now_timestamp(),
            )
            return

        self.started.emit()

        thread = QThread()
        worker = _LLMWorker(payload, config, self._transport)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._on_worker_finished)
        worker.finished.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._clear_refs)
        self._thread = thread
        self._worker = worker
        thread.start()

    @Slot(object)
    def _on_worker_finished(self, response: LLMResponse) -> None:
        ts = _now_timestamp()
        if response.ok:
            text = response.response_text or "(empty response)"
            self.finished_ok.emit(text, ts)
        else:
            self.finished_error.emit(_friendly_error_text(response), ts)

    @Slot()
    def _clear_refs(self) -> None:
        self._thread = None
        self._worker = None
