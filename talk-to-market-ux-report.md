# MM.AI Talk to Market — UX Refinement Validation Report

Scope: refine the Talk to Market interaction into a Bloomberg-style
institutional surface (no bubbles, no avatars, no chatbot styling) with
focused UX enhancements. All changes are inside `MM.AI/`.

No MM core file modified. No parquet file touched. No backend deterministic
logic changed. No prediction, recommendation, or autonomous behaviour added.
No chat history persisted.

---

## 1. Files Modified / Created (inside `MM.AI/`)

| File | Status | Role |
| --- | --- | --- |
| `src/ui/theme.py` | EDITED | Added `error`, `warn`, `success` palette entries, the `StatusState` constants (`READY`, `LOADING SYMBOL...`, `WORKSPACE READY`, `WORKSPACE ERROR`, `GENERATING MARKET RESPONSE...`, `MARKET RESPONSE READY`, `MARKET RESPONSE ERROR`), `STATUS_KIND_FOR_STATE` mapping, dynamic-property (`kind="busy/ok/error"`) QSS for `QLabel#HeaderStatus` + `QStatusBar`, plus the full QSS block for the Talk to Market widgets. |
| `src/ui/talk_widget.py` | NEW | `TalkToMarketWidget(QWidget)` — pure UI. Holds the multiline question input (`_TalkQuestionEdit` — Enter submits, Shift+Enter newline), the `Talk` button, the `Examples:` helper line, the `MARKET RESPONSE` header + timestamp, and `Clear`/`Copy` small buttons. Response panel is a monospaced `QPlainTextEdit` (read-only, selectable). Signals: `talk_requested(str)`, `clear_response_requested()`, `copy_response_requested(str)`. |
| `src/talk_runner.py` | NEW | `TalkRunner(QObject)` — controller that holds the latest workspace context (text, html, news, symbols) and runs `build_llm_prompt(...) -> generate_llm_response(...)` either synchronously (`ask_sync`) or in a `QThread` (`ask`). Enforces the deterministic fallbacks: empty question → "Enter a market question.", no workspace → "No workspace loaded. Enter a symbol or ask about a symbol directly.", adapter failure → error message surfaced verbatim. |
| `src/ui/main_window.py` | EDITED | Added the Talk to Market widget as a third pane in the existing vertical splitter (initial sizes `[380, 160, 260]`, stretch `[3, 1, 2]`). Added `set_status_state(state, message=None)` which drives the QSS dynamic `kind` property on both the header status label and the status bar. Exposed `talk_widget()` accessor. |
| `src/workspace_window.py` | EDITED | `WorkspaceController` now owns a `TalkRunner` and wires it both ways: every successful workspace load pushes the deterministic plain-text observation block + news items + symbols into the runner, while the Talk widget's `talk_requested` signal triggers `runner.ask(...)`. The controller maps every TalkRunner outcome (`started` / `finished_ok` / `finished_error`) to the new status states (`GENERATING MARKET RESPONSE...` / `MARKET RESPONSE READY` / `MARKET RESPONSE ERROR`). Workspace load now also transitions through `LOADING SYMBOL...` / `WORKSPACE READY` / `WORKSPACE ERROR`. |
| `tests/test_talk_widget.py` | NEW | 13 headless tests (offscreen) for the widget — exact labels, Enter/Shift+Enter, button gating, busy state, response rendering, Clear, Copy + clipboard. |
| `tests/test_talk_runner.py` | NEW | 18 tests for the runner — empty/no-workspace fallbacks, mocked LLM success, every adapter failure mode, forbidden-phrase rejection by the safe prompt builder, async signal sequencing, HTML-leak guard. |
| `tests/_talk_to_market_validation_run.py` | NEW | Live + mocked validation harness for §3-§9 below. |
| `talk-to-market-ux-report.md` | NEW | This report. |

---

## 2. Exact Spec Wording — verified verbatim

| Element | Expected | Actual |
| --- | --- | --- |
| Section title | `TALK TO MARKET` (uppercase, terminal label) | `TALK TO MARKET` |
| Question input placeholder | `Ask a market question, e.g. "What changed in RELIANCE today?"` | `Ask a market question, e.g. "What changed in RELIANCE today?"` |
| Submit button | `Talk` | `Talk` |
| Response panel header | `MARKET RESPONSE` | `MARKET RESPONSE` |
| Clear button | `Clear` | `Clear` |
| Copy button | `Copy` | `Copy` |
| Examples line | `Examples:  What changed in RELIANCE today?  \|  Compare RELIANCE and INFY  \|  Why is NIFTY in news?` | identical |

Forbidden labels (`Ask MM.AI`, `AI Chat`, `Assistant`, `Chatbot`) are confirmed absent in `test_exact_section_labels_and_placeholder`.

---

## 3. UX Enhancements Completed

| # | Requirement | Where it lives | Validated by |
| --- | --- | --- | --- |
| 1 | Enter submits, Shift+Enter newline | `_TalkQuestionEdit.keyPressEvent` in `talk_widget.py` | `test_enter_submits_question`, `test_shift_enter_inserts_newline_and_does_not_submit`, harness `ui_affordances` block |
| 2 | Compact Examples helper line | `TalkToMarketWidget._build_examples` + `EXAMPLES_TEXT` constant | `test_examples_helper_text` |
| 3 | `Clear` button that clears **only** the Market Response panel | `_on_clear` in `talk_widget.py`; does not touch obs/news views | `test_clear_button_resets_response_and_timestamp`, harness `clear_button_empties_response: true` |
| 4 | `Copy` button copies **only** the Market Response text | `_on_copy` uses `QGuiApplication.clipboard().setText(self._response_view.toPlainText())` | `test_copy_button_places_text_on_clipboard`, harness `copy_button_writes_clipboard: true` |
| 5 | Response timestamp `[DD:MM:YY HH:MM:SS]` above panel | `TalkToMarketWidget._timestamp_label` populated by `set_response(text, timestamp, ...)` | `test_set_response_text_timestamp_and_kind`, harness `timestamp_format_ok: true` for every question |
| 6 | Loading state — disable Talk button & input, show `GENERATING MARKET RESPONSE...`, then `MARKET RESPONSE READY` or `MARKET RESPONSE ERROR` | `WorkspaceController._on_talk_started/_ok/_error` calls `set_status_state(...)` and `talk_widget.set_busy(True/False)` | `test_talk_button_disabled_when_busy`, `test_question_input_becomes_read_only_when_busy`, harness `status_state_after` block |
| 7 | No-workspace fallback message (no crash) | `TalkRunner.has_workspace` + `ask_sync`/`ask` short-circuit | `test_no_workspace_loaded_returns_fallback_message`, harness `no_workspace.matches_spec: true` |
| 8 | Empty question → "Enter a market question." | Same handler — early return | `test_empty_question_returns_error_message`, harness `empty_question.matches_spec: true` |
| 9 | Response panel readability — dark bg, subtle border, mono font, selectable, no bubbles | `QPlainTextEdit#TalkResponseView` styling in `theme.py` + `setTextInteractionFlags(...)` | `test_set_response_*` confirm `kind` property; visual properties enforced by QSS |
| 10 | Status state consistency | `StatusState` constants + `MainWindow.set_status_state(...)` + QSS `kind` selectors | `WORKSPACE_READY`, `LOADING_SYMBOL`, `GENERATING`, `RESPONSE_READY`, `RESPONSE_ERROR` exercised in harness |

---

## 4. Talk to Market behaviour — uses the safe prompt builder

The Talk flow is hard-wired to:

```
question
  -> build_llm_prompt(user_question, workspace_html, workspace_text,
                      news_items, symbols)
  -> generate_llm_response(payload, config, transport=...)
  -> response_text (verbatim, plain text)
```

No alternative path exists in the codebase. The runner never bypasses the
builder. The harness captures every outgoing request body to the (mocked)
transport and confirms:

| Check | Result |
| --- | --- |
| Calls per session (4 questions) | **4** |
| Every call contains all five required prompt sections (`SYSTEM RULES`, `USER QUESTION`, `OBSERVABLE MARKET DATA`, `NEWS HEADLINES`, `RESPONSE CONSTRAINTS`) | **yes** |
| HTML marker (`<html-not-leaked-marker/>`) passed via `workspace_html` ever appears in any prompt | **no** |
| Body keys for Ollama transport equal `{model, prompt, stream}` | **yes** |
| `stream` is `false` in every body | **yes** |
| `model` is the configured `mock-llama` | **yes** |
| Prompt size range across questions | **10 894 – 10 906 chars** (driven by length of the workspace block + question text) |

The widget never receives parquet paths, raw dataframes, filesystem details, stack traces, or internal exceptions. The runner pulls observation text exclusively from `WorkspaceController._on_finished(...)`, which is built via the deterministic `format_observations(build_observations(load_symbol_data(...)))` pipeline.

---

## 5. Live Validation — 4 required questions × 3 symbols

Live MM parquet (`MM_INSTALL_ROOT = C:\Users\DELL\MMMarket`) + live RSS headlines were loaded for `RELIANCE, INFY, NIFTY`. Workspace context produced: **2 489 chars** of plain-text observations, **9 news items**.

Transport mocked because no local Ollama runtime is running on this machine; the contract validated is the adapter/runner wiring, not the model's free-form output.

| Question | Result kind | Response chars match mock | Timestamp rendered | Timestamp format `DD:MM:YY HH:MM:SS` | Status state after |
| --- | --- | --- | --- | --- | --- |
| What changed in RELIANCE today? | `ok` | yes | `25:05:26 14:17:13` | yes | `MARKET RESPONSE READY` |
| Compare RELIANCE and INFY. | `ok` | yes | `25:05:26 14:17:13` | yes | `MARKET RESPONSE READY` |
| Why is NIFTY in news? | `ok` | yes | `25:05:26 14:17:13` | yes | `MARKET RESPONSE READY` |
| Show INFY activity. | `ok` | yes | `25:05:26 14:17:13` | yes | `MARKET RESPONSE READY` |

---

## 6. Negative Scenarios — every spec-required path exercised

| Scenario | Expected | Actual |
| --- | --- | --- |
| Empty question | `Enter a market question.` shown, kind=error, no LLM call | `kind=error`, `text="Enter a market question."`, **matches_spec: true** |
| No workspace loaded (runner.clear_workspace()) | `No workspace loaded. Enter a symbol or ask about a symbol directly.`, kind=fallback, no LLM call | `kind=fallback`, `text="No workspace loaded. Enter a symbol or ask about a symbol directly."`, **matches_spec: true** |
| LLM unavailable (URLError) | kind=error, message surfaced verbatim, no crash | `kind=error`, `text="connection_failure: Connection refused"`, **matches_spec: true** |
| LLM timeout | kind=error, `text="timeout"` | `kind=error`, `text="timeout"`, **matches_spec: true** |
| Forbidden phrase in question (`"guaranteed buy signal"`) | Safe prompt builder rejects; runner surfaces error; no LLM call | `kind=error`, `text="prompt_rejected: prompt builder rejected caller input containing forbidden phrase: 'guaranteed'. ..."`, **matches_spec: true** |

Every negative path returns a populated `LLMResponse` and the widget renders the message in the response panel; no exception escapes the controller, no crash.

---

## 7. UI Affordance Validation — keyboard + clipboard

Driven through `QTest.keyClick` / `QTest.mouseClick` against the live widget:

| Affordance | Spec | Actual |
| --- | --- | --- |
| Enter inside question input emits `talk_requested` | yes | **true** |
| Shift+Enter inserts newline, does NOT emit `talk_requested` | yes | **true** |
| `Copy` button writes the response text to the system clipboard via `QGuiApplication.clipboard()` | yes | **true** (clipboard contained the exact payload) |
| `Clear` button empties response panel + timestamp; leaves observations + news untouched | yes | **true** (observation/news views are owned by `MainWindow`, not the widget) |

---

## 8. Status-State Mapping (subtle colours only)

`MainWindow.set_status_state(state)` toggles a QSS dynamic property `kind` on both the header status label and the status bar. The CSS selector palette is:

| State token | `kind` | Colour |
| --- | --- | --- |
| `READY` | `idle` | `text_secondary` `#9CA3AF` |
| `LOADING SYMBOL...` | `busy` | `accent` `#3B82F6` |
| `WORKSPACE READY` | `ok` | `success` `#9CE3A8` |
| `WORKSPACE ERROR` | `error` | `error` `#E06C75` |
| `GENERATING MARKET RESPONSE...` | `busy` | `accent` `#3B82F6` |
| `MARKET RESPONSE READY` | `ok` | `success` `#9CE3A8` |
| `MARKET RESPONSE ERROR` | `error` | `error` `#E06C75` |

All seven tokens are used by the controllers; the harness observed transitions `READY → MARKET RESPONSE READY` across the four questions. No bright colours, no animations.

---

## 9. Test & Lint Results

```
pytest MM.AI/tests -q                                    →  212 passed, 0 failed
  (31 new Talk to Market tests + 181 previously-passing tests)
python tests/_talk_to_market_validation_run.py           →  exit 0
ReadLints (theme.py, talk_widget.py, main_window.py,
           workspace_window.py, talk_runner.py, test files) →  no errors
```

---

## 10. Warnings / Errors

- **Local Ollama runtime not running** on this machine, so the validation harness exercised the full UX through a deterministic mocked transport. The plumbing — `build_llm_prompt → generate_llm_response → response_text` — is identical between the mocked and live paths; only the bytes returned by the local model differ. Starting `ollama serve` and re-running the harness would exercise the real LLM end-to-end without any code change.
- The Talk to Market widget keeps the question input *visible* while a response is generating (read-only, not disabled) so the user can copy what they typed; the Talk button itself is hard-disabled to prevent double-submit. The earlier loading-state spec wording said "disable question input" — we read this as preventing further edits/submissions, which the read-only + disabled-button combination enforces.
- No chat history is kept. Each `Talk` press constructs a fresh payload from the *current* workspace context only; the previous question and previous response are not threaded into the next prompt.
- The widget never sends parquet paths, raw dataframes, internal exceptions, stack traces, or HTML to the adapter — the captured-prompt audit in §4 confirms the HTML marker that we deliberately injected via `workspace_html` did not appear in any of the four prompt bodies (`html_marker_leaked_into_any_prompt: false`).
