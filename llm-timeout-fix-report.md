# Local LLM Timeout Configuration Fix Report

Raised the local-LLM request timeout default, surfaced the configured
duration in the user-facing error string, and confirmed end-to-end
that an 85-second `qwen2.5:7b` round-trip now completes instead of
hitting the previous 60-second cap.

No MM core file was touched. No parquet file was read or written. The
safe prompt builder remains the only path to the LLM and the local LLM
adapter remains the only transport.

## 1. Files modified / created

| File | Status | Purpose |
| --- | --- | --- |
| `src/llm_config.py` | modified | `DEFAULT_TIMEOUT_SECONDS = 120.0` (was `60.0`). Env override + invalid-fallback + clamp behaviour unchanged. |
| `src/llm_adapter.py` | modified | The `socket.timeout` / `TimeoutError` branch now embeds the configured timeout in the error token: `timeout: <N>` where `N = int(round(config.timeout_seconds))`. Token still starts with `"timeout"` so any prior caller pattern-matching on the prefix keeps working. |
| `src/talk_runner.py` | modified | New `_extract_timeout_seconds(error)` parses `timeout: <N>` (also accepts `timeout: 60s`, `timeout: 90.5`). `_friendly_error_text` renders `"Local model request timed out after <N> seconds."` when a value is present and falls back to the generic `"Local model request timed out."` otherwise. |
| `tests/test_llm_adapter.py` | modified | Updated `test_defaults_when_no_env`, `test_invalid_timeout_falls_back_to_default`, `test_timeout_is_reported_as_timeout` to expect the new default + new token format. |
| `tests/test_ollama_endpoint_fix.py` | modified | Replaced the generic timeout-friendly test with five cases covering the new `<N> seconds` rendering, float values, `s` suffix, and zero-value guard. |
| `tests/test_talk_runner.py` | modified | The two timeout assertions now expect `"...after 5 seconds."` since the test `_cfg()` builds a config with `timeout_seconds=5.0`. |
| `tests/test_llm_timeout_fix.py` | **NEW** | 22 focused unit tests for the default constant, env override matrix, clamping, adapter token format, friendly translator, and stack-trace suppression. |
| `tests/_llm_timeout_fix_validation_run.py` | **NEW** | Live validation harness. |

## 2. Default timeout value

```
DEFAULT_TIMEOUT_SECONDS = 120.0
MIN_TIMEOUT_SECONDS     = 1.0
MAX_TIMEOUT_SECONDS     = 600.0
```

```
backend_type    : ollama
model_name      : qwen2.5:7b
endpoint_url    : http://localhost:11434/api/generate
timeout_seconds : 120.0
```

Snapshot is taken from `load_config_from_env()` with **no** env vars
set.

## 3. Env override validation

From `tests/_llm_timeout_fix_validation.json` (10 cases, all matched
their expected outcome):

| `MM_AI_LLM_TIMEOUT_SECONDS` | Result |
| --- | --- |
| *(unset)* | `120.0` |
| `120` | `120.0` |
| `180` | `180.0` |
| `60` | `60.0` |
| `abc` | `120.0` (fallback) |
| `""` | `120.0` (fallback) |
| `not-a-number` | `120.0` (fallback) |
| `100000` | `600.0` (clamped to MAX) |
| `0.0001` | `1.0` (clamped to MIN) |
| `-30` | `1.0` (clamped to MIN) |

Properties:

- `load_config_from_env()` never raises for any of the rows above.
- Invalid input (`abc`, empty, `not-a-number`) silently falls back to
  the new `120.0` default — confirms `_coerce_timeout` continues to
  shield the UI from bad env values.
- Out-of-range numbers are clamped to `[MIN, MAX]` so callers cannot
  set `timeout_seconds = 0` (an infinite-wait foot-gun) or any
  arbitrarily large value.

Unit-test coverage:

- `test_default_timeout_constant_is_120`
- `test_load_config_default_timeout_is_120`
- `test_valid_positive_env_overrides[5 parametrisations]`
- `test_invalid_env_falls_back_to_120[5 parametrisations]`
- `test_env_override_does_not_crash_for_garbage`
- `test_env_value_above_cap_is_clamped`
- `test_env_value_below_floor_is_clamped`
- `test_env_value_negative_is_clamped_to_min`

## 4. Questions tested

1. `What changed in RELIANCE today?`
2. `Compare RELIANCE and NIFTY.`
3. `What changed in SBICARD today?`

These three are recorded in `questions_under_test` of the validation
JSON. They are routed through:

```
extract_symbols_from_question
   -> _start_pipeline (auto-load workspace + news)
   -> build_llm_prompt(...)
   -> generate_llm_response(payload, config)
   -> response panel
```

No path bypasses the safe prompt builder or the local LLM adapter. No
question is sent directly to the model. Observable data + news context
remain part of the prompt — the timeout fix does not remove or shorten
any safety rule.

## 5. Success / failure result

### Live success on the user's local Ollama

```
endpoint_used        : http://localhost:11434/api/generate
model                : qwen2.5:7b
timeout_seconds      : 120.0
ok                   : true
elapsed_ms           : 85041
prompt_chars         : 2158
adapter_token        : null
friendly_text        : null
response_text_chars  : 52
endpoint_probe       : alive=true, latency_ms=1012, error=null
```

The call took **85 seconds** end-to-end. Under the previous 60-second
default this exact call would have terminated as
`Local model request timed out after 60 seconds.` Under the new
120-second default it returns `ok=true` with a clean response payload.

`response_text_chars` is reported but the model output itself is never
echoed — no market interpretation is rendered by the harness.

### Status state transitions

The `WorkspaceController -> TalkRunner` plumbing was not touched by
this fix; the status sequence remains:

```
EXTRACTING SYMBOLS...
LOADING <symbol_list>...
WORKSPACE READY
GENERATING MARKET RESPONSE...        <- visible until LLM returns
MARKET RESPONSE READY                <- on success
MARKET RESPONSE ERROR                <- on timeout / failure
```

`MARKET RESPONSE ERROR` is what the response panel displays on a
timeout. Header colour is driven by the QSS `kind=error` property.

## 6. Timeout / error-handling validation

Adapter token + friendly translation, captured deterministically with
a mocked `socket.timeout`:

| `config.timeout_seconds` | `LLMResponse.error` (internal token) | Response panel text |
| --- | --- | --- |
| `120.0` | `timeout: 120` | `Local model request timed out after 120 seconds.` |
| `180.0` | `timeout: 180` | `Local model request timed out after 180 seconds.` |
| `5.0` | `timeout: 5` | `Local model request timed out after 5 seconds.` |
| `89.6` | `timeout: 90` (rounded) | `Local model request timed out after 90 seconds.` |

Backward-compat checks:

- A legacy / value-less `timeout` token still produces
  `"Local model request timed out."` so older code paths or
  third-party transports that emit the bare token continue to work.
- A `timeout: 0` token is treated as "no value" and falls back to the
  generic message — the friendly translator never lies about a
  non-positive duration.
- A `timeout: abc` token is rejected by the integer extractor — same
  generic fallback.
- A stack-trace-shaped error wrapped in `unexpected_error: …Traceback
  (most recent call last)…` is dropped entirely; the panel sees only
  `"Market response unavailable."` (`test_friendly_text_never_leaks_stack_traces`).

The `_is_local_endpoint` guard, the `endpoint_rejected` token, and the
JSON-error-body extraction for HTTP 404 from the prior endpoint-fix
work are all unaffected.

## 7. Tests

| Suite | Tests | Result |
| --- | --- | --- |
| `tests/test_llm_timeout_fix.py` | 22 | all pass |
| `tests/test_ollama_endpoint_fix.py` | 33 (was 29, +4 friendly timeout cases) | all pass |
| `tests/test_llm_adapter.py` (existing assertions updated) | 31 | all pass |
| `tests/test_talk_runner.py` (two assertions updated) | 17 | all pass |
| Full MM.AI suite (regression) | 307 | all pass |

Lints clean on every edited source / test file.

## 8. Warnings / errors

- The validation harness's live smoke takes ~85 s on the user's
  machine. Multi-symbol Talk to Market prompts will be larger and
  generate more tokens — operators that still see
  `Local model request timed out after 120 seconds.` should raise
  `MM_AI_LLM_TIMEOUT_SECONDS` (clamped ceiling is 600 s).
- The harness exited cleanly (`exit=0`, 4138-byte UTF-8 JSON, no
  unhandled exceptions).
- No parquet file, no MM core file, no UI deterministic path was
  touched. The fix is strictly inside `MM/MM.AI/src/llm_config.py`,
  `src/llm_adapter.py`, and `src/talk_runner.py`.
