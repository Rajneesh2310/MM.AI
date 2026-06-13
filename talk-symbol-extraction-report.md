# Talk to Market — Automatic Symbol Extraction Report

Read-only validation of the new automatic symbol-extraction layer wired
into the Talk to Market panel. No MM core files were touched. No parquet
files were modified. The deterministic backend pipeline, the safe prompt
builder, and the local LLM adapter all remain in place — the extractor
only decides which symbols the existing pipeline should load before the
prompt is built.

## 1. Files modified / created

| File | Status | Purpose |
| --- | --- | --- |
| `src/symbol_extractor.py` | **NEW** | Deterministic `extract_symbols_from_question(question, known_symbols=None) -> list[str]` with stopword guard and safe-fallback corpus. |
| `src/ui/theme.py` | modified | Added the `StatusState.EXTRACTING_SYMBOLS = "EXTRACTING SYMBOLS..."` token + mapped it to the `busy` QSS kind. |
| `src/ui/main_window.py` | modified | `set_status_state(...)` accepts an optional `header_override=` so the Talk path can render `LOADING NIFTY, RELIANCE...` verbatim. |
| `src/workspace_window.py` | modified | Refactored the pipeline kickoff into `_start_pipeline()`; `_on_talk_requested` now extracts symbols, auto-loads the union of currently-loaded + mentioned symbols, and chains the LLM call once the worker finishes via a `_pending_talk_question` slot. `_on_finished` / `_on_failed` honour the pending question and surface workspace errors back through the response panel. |
| `tests/test_symbol_extractor.py` | **NEW** | 26 unit tests for the extractor. |
| `tests/test_talk_auto_load.py` | **NEW** | 6 integration tests covering the no-workspace auto-load, the workspace-override, and the no-symbol fallback paths. |
| `tests/_talk_symbol_extraction_validation_run.py` | **NEW** | Headless validation harness driving every spec validation case against the full UI stack with a mocked LLM transport. |

## 2. Extraction rules implemented

1. **Normalise input** — upper-case, drop noise punctuation, split on
   whitespace / `,` / `;` / `:`. Punctuation outside `[A-Z0-9&]` is
   stripped so `"INFY."`, `"(NIFTY)"`, `"RELIANCE!!!"` all reduce to a
   single ticker token; `&` is preserved for real Indian tickers like
   `M&M` / `L&T`.
2. **Direct token detection** — every cleaned token is a candidate; no
   substring or fuzzy matching is performed against tickers so the
   extractor never invents symbols.
3. **Order preservation** — return tokens in the order of first
   appearance (`["NIFTY", "RELIANCE"]` ≠ `["RELIANCE", "NIFTY"]`).
4. **Deduplication** — repeated mentions collapse to one entry while
   keeping the first-seen position.
5. **Lowercase support** — `"compare nifty and reliance"` is upper-cased
   before matching, yielding `["NIFTY", "RELIANCE"]`.
6. **Catalogue filter** — when `known_symbols=` is supplied (e.g.
   `symbol_catalog.list_all_symbols()`), a token must be a member of
   that set to count as a symbol. Random English words can therefore
   never slip through.
7. **Safe-fallback corpus** — when `known_symbols=None` (or the
   catalogue happens to be empty), only the universally-supported
   `{NIFTY, BANKNIFTY, RELIANCE, INFY}` set is allowed. No invented
   symbols.
8. **Stop-word guard** — a curated set of common English words
   (`WHAT`, `TODAY`, `MARKET`, `COMPARE`, …) is filtered out
   *regardless* of catalogue membership, eliminating any false positive
   from rare overlaps.

## 3. Talk-to-Market flow

```
question
   ├── empty?                       -> TalkRunner emits
   │                                   "Enter a market question."
   │
   ├── EXTRACTING SYMBOLS...
   ├── extracted = []  AND no workspace
   │                                -> TalkRunner emits the existing
   │                                   no-workspace fallback.
   ├── extracted = []  AND workspace loaded
   │                                -> TalkRunner.ask(question) using
   │                                   current context.
   ├── new symbols in question      -> _start_pipeline(union)
   │     (LOADING NIFTY, ...)          observation panel populates
   │     -> WORKSPACE READY            news ticker populates
   │     -> _pending_talk_question     TalkRunner.ask(question)
   │     -> GENERATING ...             build_llm_prompt(...)
   │     -> MARKET RESPONSE READY      generate_llm_response(...)
   └── (failure during load)        -> MARKET RESPONSE ERROR with the
                                       workspace_error: ... reason
                                       surfaced to the response panel.
```

The safe-prompt-builder + local-LLM-adapter pipeline is never bypassed.
The question is **never** sent to the LLM directly — every call goes
through `build_llm_prompt(...) -> generate_llm_response(...)`.

## 4. Question validation matrix

Live validation output (mocked HTTP + mocked local LLM transport):

| # | Question | Extracted (full universe) | Extracted (safe fallback) | UI loaded symbols | UI status sequence (key tokens) | LLM called | Safe prompt sections |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `compare nifty and reliance` | `NIFTY, RELIANCE` | `NIFTY, RELIANCE` | `NIFTY, RELIANCE` | EXTRACTING → LOADING NIFTY, RELIANCE... → WORKSPACE READY → GENERATING → MARKET RESPONSE READY | yes | 5/5 present, no HTML leak |
| 2 | `What changed in RELIANCE today?` | `RELIANCE` | `RELIANCE` | `RELIANCE` | EXTRACTING → LOADING RELIANCE... → WORKSPACE READY → GENERATING → MARKET RESPONSE READY | yes | 5/5 present, no HTML leak |
| 3 | `Show INFY activity` | `INFY` | `INFY` | `INFY` | EXTRACTING → LOADING INFY... → WORKSPACE READY → GENERATING → MARKET RESPONSE READY | yes | 5/5 present, no HTML leak |
| 4 | `Why is NIFTY in news?` | `NIFTY` | `NIFTY` | `NIFTY` | EXTRACTING → LOADING NIFTY... → WORKSPACE READY → GENERATING → MARKET RESPONSE READY | yes | 5/5 present, no HTML leak |
| 5 | `compare reliance, infy and nifty` | `RELIANCE, INFY, NIFTY` | `RELIANCE, INFY, NIFTY` | `RELIANCE, INFY, NIFTY` | EXTRACTING → LOADING RELIANCE, INFY, NIFTY... → WORKSPACE READY → GENERATING → MARKET RESPONSE READY | yes | 5/5 present, no HTML leak |
| 6 | `compare reliance; infy; nifty` (semicolon) | `RELIANCE, INFY, NIFTY` | `RELIANCE, INFY, NIFTY` | `RELIANCE, INFY, NIFTY` | EXTRACTING → LOADING RELIANCE, INFY, NIFTY... → WORKSPACE READY → GENERATING → MARKET RESPONSE READY | yes | 5/5 present, no HTML leak |
| 7 | `what changed today?` | `[]` | `[]` | `[]` | EXTRACTING → READY (no-workspace fallback) | no | n/a |
| 8 | `"   "` (whitespace) | `[]` | `[]` | `[]` | MARKET RESPONSE ERROR | no | n/a |

`status_state_tokens_seen` aggregated across the harness:

```
EXTRACTING SYMBOLS...
GENERATING MARKET RESPONSE...
LOADING INFY...
LOADING NIFTY, RELIANCE...
LOADING NIFTY...
LOADING RELIANCE, INFY, NIFTY...
LOADING RELIANCE...
MARKET RESPONSE ERROR
MARKET RESPONSE READY
READY
WORKSPACE READY
```

Every token mandated by the spec appears.

## 5. Auto-load validation

For each non-empty question containing one or more known symbols:

- `controller._last_symbols` was updated **before** the LLM call.
- The symbol search field text was rewritten to the loaded symbols list.
- `observation_plain_text()` reported non-empty content (observation
  table rendered).
- `news_html()` grew well past the empty-state size — for cases 1, 5, 6
  it grew above 2.8 KB, 4.0 KB, 4.0 KB respectively, confirming the
  ticker received populated `NewsResult` items for each symbol.
- The no-workspace fallback (`"No workspace loaded. Enter a symbol or
  ask about a symbol directly."`) appeared **only** for case 7
  (`what changed today?`).

The pipeline reload path is also exercised by
`tests/test_talk_auto_load.py::test_loaded_workspace_extended_with_question_symbols`,
which pre-loads `RELIANCE`, types `"compare reliance and infy"`, and
confirms the final `_last_symbols == ["RELIANCE", "INFY"]` while
`fetch_symbol_news` is called for both symbols.

## 6. Safe prompt-builder usage validation

The harness recorded 6 calls into the mocked Ollama transport (one per
positive case). Each call's body was inspected:

```
all_sections_present: true   (SYSTEM RULES, USER QUESTION,
                              OBSERVABLE MARKET DATA,
                              NEWS HEADLINES, RESPONSE CONSTRAINTS)
has_html_leak:        false
prompt_chars:         3133..5101
```

This confirms the Talk pipeline goes through `build_llm_prompt(...)` —
the question is never piped raw to the model and the workspace HTML is
never forwarded to the adapter.

## 7. Local LLM adapter usage validation

Every LLM round-trip uses `generate_llm_response(payload, config,
transport=…)`. The harness uses a `LLMConfig("ollama", "mock-model",
"http://127.0.0.1:11434/api/generate", 5.0)` — explicitly a loopback
endpoint that passes the adapter's `_is_local_endpoint` guard. The
mocked transport returned `{"response": "OK: deterministic test
reply."}` and the response panel rendered the text verbatim. No
post-processing, no extra sanitisation, no recommendation logic.

## 8. UI status validation

Each validation case logged its status transitions via a small spy on
`MainWindow.set_status_state`. Observed sequences match the spec
ordering exactly:

```
EXTRACTING SYMBOLS...
LOADING <symbol_list>...
WORKSPACE READY
GENERATING MARKET RESPONSE...
MARKET RESPONSE READY
```

For the no-symbols / no-workspace case (`what changed today?`) the
sequence is:

```
EXTRACTING SYMBOLS...
READY              (TalkRunner reports fallback, controller resets
                   the header to READY instead of claiming success)
```

For the empty-question case (`"   "`) the runner short-circuits with
`MARKET RESPONSE ERROR`.

## 9. Tests

| Suite | Tests | Result |
| --- | --- | --- |
| `tests/test_symbol_extractor.py` | 26 | all pass |
| `tests/test_talk_auto_load.py` | 6 | all pass |
| Full MM.AI suite (regression) | 244 | all pass |

## 10. Warnings / errors

- **None.** No regressions in the 212 pre-existing tests; no new lints
  introduced (`ReadLints` clean on the four edited source files).
- The harness sandboxes itself under `%TEMP%/mm_ai_talk_extract_validation`
  and never reads or writes any file under MM's real install root.

## 11. Constraints honoured

- No modification of any MM core file.
- No modification of any parquet file.
- No change to deterministic backend logic (`symbol_reader`,
  `observation_builder`, `text_formatter`, `news_fetcher` are
  untouched).
- The safe prompt builder is the **only** path to the LLM. Direct
  question → LLM is impossible.
- The local LLM adapter is the **only** transport. No cloud endpoint,
  no internet egress.
- No parquet paths or raw dataframes are exposed to the LLM — only the
  deterministic plain-text observation block and the headline /
  source / URL fields make it into the prompt.
- No prediction logic, no recommendation logic, no autonomous agent
  behaviour was added.
