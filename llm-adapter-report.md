# MM.AI Local-LLM Adapter — Validation Report

Scope: minimal local-only adapter that connects the existing safe prompt
builder to a local LLM runtime (Ollama or any OpenAI-compatible local
server). No cloud APIs. No internet egress. No tool-calling. No memory.
No autonomy.

---

## 1. Files Delivered (inside `MM.AI/`)

| File | Role |
| --- | --- |
| `src/llm_response_models.py` | Frozen `LLMResponse` dataclass. Fields: `ok`, `backend`, `model`, `endpoint`, `timestamp`, `response_text`, `error`, `elapsed_ms`, `prompt_chars`. Exposes `.as_dict()`. |
| `src/llm_config.py` | Frozen `LLMConfig` + `load_config_from_env()`. Env vars: `MM_AI_LLM_BACKEND`, `MM_AI_LLM_MODEL`, `MM_AI_LLM_ENDPOINT`, `MM_AI_LLM_TIMEOUT_SECONDS`. Defaults per backend; timeout clamped to [1, 600] s. |
| `src/llm_adapter.py` | `generate_llm_response(prompt_payload, config=None, *, transport=None) -> LLMResponse`. Dispatches to Ollama (`/api/generate`) or OpenAI-compat (`/v1/chat/completions`). Local-endpoint guard refuses public hosts before any transport call. Never raises. Also exposes `probe_endpoint(config)`. |
| `tests/test_llm_adapter.py` | 37 unit tests, all transport calls mocked. |
| `tests/_llm_adapter_validation_run.py` | Live + mocked validation harness used to produce §6 / §7. |

No MM core file modified. No cloud SDK installed. No `requests`, `openai`, or similar imported.

---

## 2. Public API

```python
from src.llm_prompt_builder import build_llm_prompt
from src.llm_adapter import generate_llm_response
from src.llm_config import load_config_from_env

payload = build_llm_prompt(
    user_question="What changed in RELIANCE today?",
    workspace_html=None,
    workspace_text="<format_observations() output>",
    news_items=[...],
    symbols=["RELIANCE"],
)
config = load_config_from_env()  # or hand-build an LLMConfig
response = generate_llm_response(payload, config)

# response.as_dict() ->
# {
#   "ok": True,
#   "backend": "ollama",
#   "model": "llama3.2",
#   "endpoint": "http://localhost:11434/api/generate",
#   "timestamp": "25:05:26 13:01:04",
#   "response_text": "<verbatim model text>",
#   "error": None,
#   "elapsed_ms": 312,
#   "prompt_chars": 5337
# }
```

`generate_llm_response` never raises. Every failure mode is surfaced via `ok=False` and a deterministic `error` token.

---

## 3. Backends Supported

| Backend | Endpoint (default) | Request body |
| --- | --- | --- |
| `ollama` | `http://localhost:11434/api/generate` | `{"model": ..., "prompt": <prompt_text>, "stream": false}` |
| `openai_compatible` | `http://localhost:8000/v1/chat/completions` | `{"model": ..., "messages": [{"role": "user", "content": <prompt_text>}], "stream": false}` |

No other keys are sent. Adapter does not transmit conversation history, tools, function definitions, system messages, or any field outside the documented bodies (tests `test_adapter_sends_only_prompt_text_for_ollama` and `test_adapter_sends_only_messages_for_openai_compat` enforce this).

---

## 4. Security Posture

| Concern | Mechanism |
| --- | --- |
| Cloud API calls | Endpoint URL is parsed; the host must be `localhost`/`127.0.0.1`/`0.0.0.0`/`::1` *or* resolve to a loopback or RFC1918 private address. Anything else returns `ok=False, error="endpoint_rejected: ..."` **before any transport call**. |
| Unsupported scheme | Only `http`/`https` accepted. `ftp://localhost/...` rejected. |
| Public IP literal | `http://8.8.8.8/...` rejected with `non_local_endpoint`. |
| Hostname that resolves publicly | DNS lookup performed once; public resolution rejected. |
| Cloud SDKs | None imported. Adapter uses stdlib `urllib.request` only. |
| Tool-calling / function-calling | Not implemented. Adapter speaks `/api/generate` (Ollama) and `/v1/chat/completions` (single user message) only. |
| Memory / history | Not implemented. Each call is independent. |
| Streaming | Disabled (`stream: false`) on both backends. |
| Retries | None. Single attempt, deterministic error object on failure. |
| Post-processing | None. Model text returned verbatim (test `test_response_text_is_preserved_verbatim` validates Unicode, tabs, blank lines, emoji all preserved). |
| Hidden data leakage | Adapter only reads `prompt_payload.prompt_text` from the `LLMPromptPayload`. The safe prompt builder is responsible for ensuring that text contains no parquet paths / dataframes / tracebacks. |

---

## 5. Configuration Surface

| Env var | Default (per backend) | Notes |
| --- | --- | --- |
| `MM_AI_LLM_BACKEND` | `ollama` | Must be one of `ollama`, `openai_compatible`. Anything else raises `ValueError` during `load_config_from_env()`. |
| `MM_AI_LLM_MODEL` | `llama3.2` (ollama) / `local-model` (openai-compat) | Free-form string sent verbatim as `model`. |
| `MM_AI_LLM_ENDPOINT` | `http://localhost:11434/api/generate` / `http://localhost:8000/v1/chat/completions` | Must resolve to a local address. |
| `MM_AI_LLM_TIMEOUT_SECONDS` | `60` | Coerced to float; clamped to `[1, 600]`. Non-numeric falls back to default. |

---

## 6. Live + Mocked Validation — three required questions

Environment for this run:

```
config.backend_type    = ollama
config.model_name      = llama3.2
config.endpoint_url    = http://localhost:11434/api/generate
config.timeout_seconds = 60.0
probe                  = {"alive": false, "latency_ms": 3015, "error": "TimeoutError: timed out"}
```

A live Ollama runtime was **not running** on this machine, so the harness exercised both backends through a deterministic mocked transport. (If you start Ollama at the same endpoint and re-run `tests/_llm_adapter_validation_run.py`, a third `live_ollama` row will be added per question.)

| Question | Symbols | Prompt chars | Backend exercised | OK | Backend | Endpoint | Response chars | Error |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| What changed in RELIANCE today? | RELIANCE | 5 337 | mocked_ollama | yes | ollama | `http://127.0.0.1:11434/api/generate` | 63 | none |
| What changed in RELIANCE today? | RELIANCE | 5 337 | mocked_openai_compatible | yes | openai_compatible | `http://127.0.0.1:8000/v1/chat/completions` | 66 | none |
| Compare RELIANCE and INFY. | RELIANCE, INFY | 7 304 | mocked_ollama | yes | ollama | `http://127.0.0.1:11434/api/generate` | 58 | none |
| Compare RELIANCE and INFY. | RELIANCE, INFY | 7 304 | mocked_openai_compatible | yes | openai_compatible | `http://127.0.0.1:8000/v1/chat/completions` | 61 | none |
| Why is NIFTY in news? | NIFTY | 5 131 | mocked_ollama | yes | ollama | `http://127.0.0.1:11434/api/generate` | 53 | none |
| Why is NIFTY in news? | NIFTY | 5 131 | mocked_openai_compatible | yes | openai_compatible | `http://127.0.0.1:8000/v1/chat/completions` | 56 | none |

**Prompt-generation validation (every row above):**
- The prompt passed to the adapter was produced by `build_llm_prompt(...)` over live MM parquet + live RSS headlines for each symbol.
- `prompt_chars` matches the size of the verbatim payload received by the transport (verified by the unit tests `test_ollama_request_shape_and_response_extraction` and `test_openai_compat_request_shape_and_choice_extraction`).

**Response-generation validation:**
- `response_text` returned by the adapter equals byte-for-byte the canned text supplied to the mock transport. No trimming, no whitespace normalisation, no extra interpretation appended. Unit test `test_response_text_is_preserved_verbatim` covers Unicode, tabs, blank lines, and emoji.

---

## 7. Timeout / Error-Handling Validation

| Scenario | Transport behaviour | Expected outcome | Actual outcome (matches?) |
| --- | --- | --- | --- |
| timeout | `socket.timeout` | `ok=false, error="timeout"` | `error="timeout"` — yes |
| connection_failure | `urllib.error.URLError("Connection refused")` | `ok=false, error~="connection_failure"` | `error="connection_failure: Connection refused"` — yes |
| invalid_json | `json.JSONDecodeError` | `ok=false, error~="invalid_json"` | `error="invalid_json: expected value: line 1 column 1 (char 0)"` — yes |
| malformed_response_missing_field | Returns `{"done": true}` (no `response` key) | `ok=false, error~="missing_response_field"` | `error="malformed_response: missing_response_field"` — yes |
| public_endpoint_blocked | Endpoint set to `http://8.8.8.8/v1/chat/completions`; transport must not be invoked | `ok=false, error~="endpoint_rejected"`; transport never called | `error="endpoint_rejected: non_local_endpoint: 8.8.8.8"`; transport assertion confirms it was not called — yes |

In every failure case the returned object is a fully populated `LLMResponse` with `response_text == ""`, a deterministic timestamp, and the original `backend`/`model`/`endpoint`/`prompt_chars` preserved for diagnostics.

Additional error modes covered by unit tests (`tests/test_llm_adapter.py`) but not re-exercised in the live harness:
- `HTTPError` with non-2xx status → `error="http_error: <code> <reason>"`.
- Ollama response of wrong type (e.g. list) → `error="malformed_response: unexpected_response_type: ..."`.
- OpenAI-compat response with empty `choices` → `error="malformed_response: missing_choices"`.
- OpenAI-compat response missing `message.content` → `error="malformed_response: missing_content"`.
- Caller passes a non-`LLMPromptPayload` object → `error="invalid_payload: expected LLMPromptPayload"`.
- Unknown runtime exception from transport (e.g. `RuntimeError`) → `error="unexpected_error: <Type>: <msg>"`.
- Invalid `MM_AI_LLM_BACKEND` value → `ValueError` from `load_config_from_env()`, surfaced via `config_error` in the response when called through `generate_llm_response()` with `config=None`.

---

## 8. Test & Lint Results

```
pytest MM.AI/tests -q                                  →  139 passed, 0 failed
  (37 adapter tests + 26 prompt-builder tests +
   76 previously-passing parquet/UI/news tests)
python tests/_llm_adapter_validation_run.py            →  exit 0
ReadLints (llm_adapter, llm_config, llm_response_models,
           test_llm_adapter, validation runner)         →  no errors
```

---

## 9. Warnings / Errors

- **Local Ollama runtime not detected** during this validation run (TCP probe to `127.0.0.1:11434` timed out at 3015 ms). The adapter is fully wired and tested via mocked transport; if you start Ollama (`ollama serve` + `ollama pull llama3.2`) and re-run the harness, the `live_ollama` row will be added to each question's `runs` block.
- The local-endpoint guard performs a DNS lookup for non-IP hostnames. A misconfigured `MM_AI_LLM_ENDPOINT` pointing to a hostname that fails to resolve returns `endpoint_rejected: resolve_failure: ...` rather than attempting any network egress.
- The adapter ignores any extra keys returned by the model server (e.g. Ollama's `done`, `total_duration`, `prompt_eval_count`; OpenAI-compat's `usage`, `id`, `finish_reason`). Only the text payload is exposed via `response_text`.
- `probe_endpoint` is a passive TCP probe — it opens and closes a socket without sending any model payload. It exists for harness use; production callers do not need to invoke it.
- No prediction, recommendation, sentiment, or interpretation logic exists in this layer. The adapter is a strict pass-through between the safe prompt builder and a local model server.
