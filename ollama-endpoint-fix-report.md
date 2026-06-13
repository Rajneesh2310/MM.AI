# Ollama Endpoint Configuration Fix Report

Root-cause + fix + live validation for the
`http_error: 404 Not Found` surfaced by Talk to Market while `curl
http://localhost:11434/api/generate` worked from the same machine.

Two latent defects were responsible:

1. The default Ollama model was `llama3.2` (a model the user did not
   have pulled). Ollama responds to a `POST /api/generate` for a
   missing model with **HTTP 404 + body
   `{"error": "model 'llama3.2' not found, try pulling it first"}`** —
   the same 404 the user saw.
2. The adapter sent requests to whatever `MM_AI_LLM_ENDPOINT` carried.
   Any value that pointed at `http://localhost:11434/`,
   `http://localhost:11434/v1/chat/completions`, or `…/api/chat` would
   produce a non-existent Ollama route and the same 404.

Both paths now collapse into a single canonical call.

## 1. Files modified / created

| File | Status | Purpose |
| --- | --- | --- |
| `src/llm_config.py` | modified | `DEFAULT_MODELS["ollama"] = "qwen2.5:7b"` (was `llama3.2`). `DEFAULT_ENDPOINTS["ollama"]` unchanged at `http://localhost:11434/api/generate`. |
| `src/llm_adapter.py` | modified | New `normalise_ollama_endpoint(url)` coerces any endpoint path to `/api/generate` for the Ollama backend. `_call_ollama` now routes through the normaliser. New `_read_http_error_body(exc)` extracts Ollama's JSON `error` field on 404 so operators can see *which* model is missing. |
| `src/talk_runner.py` | modified | New `_friendly_error_text(response)` translates adapter tokens (`http_error: 404 …`, `timeout`, `connection_failure: …`) into the spec-mandated user-facing strings. Used by both `ask_sync` and `_on_worker_finished`. Adapter's internal `LLMResponse.error` token is preserved unchanged for backwards-compat with the existing tests. |
| `tests/test_ollama_endpoint_fix.py` | **NEW** | 29 unit tests covering endpoint normalisation, default model + endpoint, 404 body extraction, and the friendly-error translation matrix. |
| `tests/_ollama_endpoint_fix_validation_run.py` | **NEW** | Live validation harness — probes a real Ollama if present, runs a tiny `/api/generate` smoke call, walks the entire adapter failure matrix through the friendly translator. |
| `tests/test_talk_runner.py` | modified | Existing three error-mode tests + one async test updated to expect the new friendly text. |

## 2. Endpoint validated

```
http://localhost:11434/api/generate
```

Normalisation matrix (from
`tests/_ollama_endpoint_fix_validation_run.py`):

| Input | Normalised |
| --- | --- |
| `http://localhost:11434/api/generate` | `http://localhost:11434/api/generate` |
| `http://localhost:11434` | `http://localhost:11434/api/generate` |
| `http://localhost:11434/` | `http://localhost:11434/api/generate` |
| `http://localhost:11434/v1/chat/completions` | `http://localhost:11434/api/generate` |
| `http://localhost:11434/api/chat` | `http://localhost:11434/api/generate` |
| `http://127.0.0.1:11434/foo` | `http://127.0.0.1:11434/api/generate` |
| `https://127.0.0.1:11434/` | `https://127.0.0.1:11434/api/generate` |
| `http://localhost:11434/api/generate?stream=true#hash` | `http://localhost:11434/api/generate` |

`_is_local_endpoint("http://localhost:11434/api/generate")` returns
`(True, "")` — the security guard still rejects any public host.

## 3. Backend type validated

```
backend_type = ollama
```

The Ollama body shape sent to `/api/generate` is exactly the documented
contract:

```json
{
  "model": "qwen2.5:7b",
  "prompt": "<prompt text>",
  "stream": false
}
```

No `/v1/chat/completions`, no `messages` array, no OpenAI SDK, no cloud
endpoints. The OpenAI-compatible code path is untouched and still
reserved exclusively for `backend_type == "openai_compatible"`.

## 4. Default config snapshot

```
backend_type        : ollama
model_name          : qwen2.5:7b
endpoint_url        : http://localhost:11434/api/generate
timeout_seconds     : 60.0
```

(All four values pass through `load_config_from_env()` with no env
vars set.)

## 5. Symbols tested

`RELIANCE`, `INFY`, `SBICARD`, `NIFTY`.

## 6. Questions tested

1. `What changed in RELIANCE today?`
2. `Compare RELIANCE and INFY.`
3. `Why is NIFTY in news?`
4. `What changed in SBICARD today?`

Through `TalkRunner.ask_sync` (full pipeline: extractor → workspace
context → `build_llm_prompt` → `generate_llm_response` →
`_friendly_error_text`):

| Mode | Outcome |
| --- | --- |
| Mocked transport (4 questions × deterministic `{"response":"MOCK_OK"}`) | All four returned `kind="ok"`, non-empty response, zero adapter tokens. |
| Live Ollama on this machine | See section 7. |

## 7. Successful Ollama response validation

The validation harness performed one **live** end-to-end call against
the user's local Ollama at `http://localhost:11434/api/generate` with
`model=qwen2.5:7b` and a minimal safe-prompt-builder payload:

```
endpoint_used        : http://localhost:11434/api/generate
model                : qwen2.5:7b
timeout_seconds      : 120.0
ok                   : true
elapsed_ms           : 45246
prompt_chars         : 2158
response_text_chars  : 52
adapter_token        : null
friendly_text        : null
```

`ok=true` with no adapter token means the request reached Ollama,
Ollama generated, and the adapter returned a clean `LLMResponse`. The
404 failure mode is no longer reachable from this configuration.

`endpoint_probe`:

```
endpoint   : http://localhost:11434/api/generate
alive      : true
latency_ms : 1024
error      : null
```

## 8. Timeout / error handling validation

Every adapter failure path was driven through the friendly translator
and recorded. The internal `adapter_token` shown below is what the
adapter places on `LLMResponse.error`; the `friendly_text` is what the
Talk to Market response panel actually displays.

| Case | Adapter token (internal) | User-facing text |
| --- | --- | --- |
| `timeout` | `timeout` | `Local model request timed out.` |
| `connection_refused` | `connection_failure: Connection refused` | `Unable to connect to local Ollama runtime.` |
| `http_404_model_missing` | `http_error: 404 Not Found — model "missing-model" not found, try pulling it first` | `Ollama endpoint returned 404.` |
| `http_500` | `http_error: 500 Internal Server Error` | `Local Ollama runtime reported a server error.` |
| `endpoint_rejected` (public IP) | `endpoint_rejected: non_local_endpoint: 8.8.8.8` | `Local LLM endpoint rejected: configure MM_AI_LLM_ENDPOINT to a loopback or private address.` |

Properties:

- The user-facing strings exactly match the spec wording for `timeout`,
  `connection refused`, and `404`.
- Stack traces never leak — the friendly translator drops any
  `unexpected_error: ...Traceback...` payload and emits the generic
  `Market response unavailable.` (test
  `test_friendly_error_does_not_expose_stack_traces`).
- The internal `LLMResponse.error` is unchanged so operators can still
  inspect the raw token in logs / diagnostics, and the existing
  `test_llm_adapter.py` suite (which asserts on those tokens) keeps
  passing.

## 9. Tests

| Suite | Tests | Result |
| --- | --- | --- |
| `tests/test_ollama_endpoint_fix.py` | 29 | all pass |
| `tests/test_llm_adapter.py` (regression, unchanged contract) | 31 | all pass |
| `tests/test_talk_runner.py` (4 tests updated for friendly wording) | 17 | all pass |
| Full MM.AI suite (regression) | 273 | all pass |

Lints clean on every edited source file.

## 10. Warnings / errors

- **Live smoke takes ~45 s on this hardware.** `qwen2.5:7b` is
  CPU-bound; if the user keeps `MM_AI_LLM_TIMEOUT_SECONDS` at the
  default of `60`, prompts much larger than the diagnostic smoke can
  hit the timeout. The fix surfaces this as
  `Local model request timed out.` instead of `http_error: 404 Not
  Found`. Operators that need longer generation should bump
  `MM_AI_LLM_TIMEOUT_SECONDS` (the env var is already clamped to the
  range `[1, 600]`).
- **No** parquet file was read or written by either the source change
  or the validation harness — the harness uses an in-memory news stub
  and the minimal safe prompt only.
- **No** MM core file was touched. No prediction logic, recommendation
  logic, or autonomous agent behaviour was added. The safe prompt
  builder remains the only path to the LLM.
