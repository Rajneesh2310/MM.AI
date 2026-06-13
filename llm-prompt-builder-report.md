# MM.AI LLM Prompt Builder — Validation Report

Scope: safe, deterministic prompt-builder layer for future local-LLM
consumption. No LLM is called. No model is connected. No answer is generated.

---

## 1. Files Delivered (inside `MM.AI/`)

| File | Role |
| --- | --- |
| `src/llm_models.py` | Immutable constants and the `LLMPromptPayload` frozen dataclass. Defines `SYSTEM_RULES`, `RESPONSE_CONSTRAINTS_ALLOWED`, `RESPONSE_CONSTRAINTS_FORBIDDEN`, `FORBIDDEN_OUTPUT_PHRASES`, length caps, and the canonical timestamp format. |
| `src/llm_prompt_builder.py` | Pure builder: `build_llm_prompt(user_question, workspace_html, workspace_text, news_items, symbols) -> LLMPromptPayload`. Sanitises every input, ignores `workspace_html`, assembles five labelled sections, asserts no forbidden phrase entered through caller content. |
| `tests/test_llm_prompt_builder.py` | 26 unit tests covering section structure, rule presence, forbidden-phrase guard, sanitisation (paths / tracebacks / dataframe reprs / control chars), input shape acceptance (`NewsItem` / `NewsResult` / dict), length caps, symbol normalisation, empty-input safety, immutability of input lists. |
| `tests/_llm_prompt_validation_run.py` | Live end-to-end harness — drives the 4 required validation questions against real MM parquet + live RSS, then prints a JSON grade. |

No MM core file modified. No real model wired up. No prediction, recommendation, sentiment, or hidden-intent path exists.

---

## 2. Public API

```python
from src.llm_prompt_builder import build_llm_prompt

payload = build_llm_prompt(
    user_question="What changed in RELIANCE today?",
    workspace_html=None,                  # accepted, never embedded
    workspace_text="<format_observations() output>",
    news_items=[NewsResult(...), NewsItem(...), {"source": ..., ...}],
    symbols=["RELIANCE"],
)
payload.as_dict()
# {
#   "timestamp": "25:05:26 12:51:14",
#   "symbols": ["RELIANCE"],
#   "question": "What changed in RELIANCE today?",
#   "prompt_text": "<assembled prompt>"
# }
```

The function returns a frozen `LLMPromptPayload`. It does **not** call any LLM, does not perform reasoning, does not produce an answer.

---

## 3. Prompt Structure

The assembled `prompt_text` always carries five sections, in this exact order, each wrapped between two 60-character `=` rule lines:

```
============================================================
SYSTEM RULES
============================================================
<deterministic-assistant intro + immutable rule bullets>

============================================================
USER QUESTION
============================================================
<sanitised question or "(no question provided)">

============================================================
OBSERVABLE MARKET DATA
============================================================
Built at: [DD:MM:YY HH:MM:SS]
Symbols: SYM1, SYM2, …

Workspace observations (already deterministic; do not reinterpret):

<sanitised workspace_text>

============================================================
NEWS HEADLINES
============================================================
Total headline references: N

[1] timestamp: ...
    source:    ...
    headline:  ...
    url:       ...
…

============================================================
RESPONSE CONSTRAINTS
============================================================
<allowed list, forbidden list, fallback reply string, citation rules>
```

Validation harness confirmed all five headers are present **and in order** for every test case (anchored regex `^={60}\n<title>\n={60}$`).

---

## 4. Immutable Rules Enforced

The `SYSTEM RULES` body contains every entry of `SYSTEM_RULES` verbatim:

1. Use observable data only.
2. Do not predict future movement.
3. Do not recommend trades.
4. Do not infer institutional intent.
5. Do not invent causation from news.
6. If data unavailable, explicitly say so.
7. Use factual language only.
8. Never claim certainty beyond provided data.
9. Do not hallucinate unavailable values.

Plus an introductory paragraph telling the future LLM that:

- the OBSERVABLE MARKET DATA and NEWS HEADLINES sections are the only ground truth,
- it must not draw on prior or external knowledge,
- missing fields must be treated as `Not Available`.

The `RESPONSE CONSTRAINTS` body emits all four allowed tokens (`concise`, `factual`, `explainable`, `observable-data-based`) and all five forbidden-behaviour labels (`bullish/bearish certainty`, `hidden smart-money claims`, `accumulation/distribution claims`, `guaranteed movement statements`, `financial advice`). It also embeds the literal fallback reply string the LLM must use when data is insufficient:

```
"I do not have enough observable data to answer that."
```

---

## 5. Sanitisation Performed (defence-in-depth)

| Input | Treatment |
| --- | --- |
| `user_question` | Unicode-NFC normalised, control chars (`\x00-\x08`, `\x0b`, `\x0c`, `\x0e-\x1f`, `\x7f`) removed, length capped to **512** chars. |
| `workspace_text` | Lines containing absolute Windows/Unix paths, `.parquet` / `.csv` / `.zip` references, `Traceback (most recent call last)` blocks, `File "…":` indented frames, Python exception lines (`<Type>Error:` / `<Type>Exception:`), and Polars `<DataFrame>` / `shape:` repr lines are dropped. Inline paths are replaced with `[redacted-path]`. Final blob length capped to **16 000** chars. |
| `workspace_html` | Accepted as a parameter for API symmetry **but never embedded** in `prompt_text`. The test `test_workspace_html_is_not_leaked_into_prompt` confirms this. |
| `news_items` | Accepts a sequence of `NewsItem`, `NewsResult` (flattened transparently), or plain dicts. Only four canonical fields kept: `source`, `headline`, `url`, `timestamp`. Any extra dict keys (e.g. `body`, `sentiment`, `analysis`) are silently discarded. Per-item caps: headline 400, url 1024, source 200. List capped to **50** items. |
| `symbols` | Stripped, upper-cased, restricted to `A–Z0–9._-&`, capped to 40 chars per symbol, max **20** symbols, deduplicated preserving order. |

A final guard scans the **caller-supplied content only** (question, sanitised workspace, news source+headline strings) against `FORBIDDEN_OUTPUT_PHRASES`. If any of `guaranteed`, `smart money`, `accumulation`, `distribution`, `buy signal`, `sell signal`, `target price`, `stop loss`, `should buy`, `should sell`, `will rally`, `will crash`, `is bullish`, `is bearish` are present in the user inputs the builder raises `ValueError` — the prompt is *not* produced.

The forbidden-behaviour labels in the RESPONSE CONSTRAINTS section (`guaranteed movement statements`, etc.) are exempt from the scan because they describe what the LLM must avoid, not what the user is saying.

---

## 6. Live Validation — 4 required questions

Live MM parquet + live Google News RSS (`MM_INSTALL_ROOT = C:\Users\DELL\MMMarket`, lookback = 5, news_limit = 5).

| Question | Symbols | News items fetched | Timestamp | Prompt chars | All 5 sections present | All 9 system rules present | Allowed tokens present | Forbidden labels present (in constraints) | Fallback reply present | Parquet path leaked | HTML leaked | Traceback leaked | Forbidden phrase in user content |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| What changed in RELIANCE today? | RELIANCE | 5 | `25:05:26 12:51:14` | 6 246 | OK | OK | OK | OK | OK | no | no | no | no |
| Compare RELIANCE and INFY. | RELIANCE, INFY | 10 | `25:05:26 12:51:15` | 9 022 | OK | OK | OK | OK | OK | no | no | no | no |
| Why is NIFTY in news? | NIFTY | 5 | `25:05:26 12:51:16` | 6 697 | OK | OK | OK | OK | OK | no | no | no | no |
| Show INFY activity. | INFY | 5 | `25:05:26 12:51:16` | 4 947 | OK | OK | OK | OK | OK | no | no | no | no |

### 6.1 Negative case — caller injects a forbidden phrase

| Case | Input | Builder raised? | Error message |
| --- | --- | --- | --- |
| `forbidden_phrase_in_question` | `Give me a guaranteed buy signal for RELIANCE.` | **yes** (`ValueError`) | `prompt builder rejected caller input containing forbidden phrase: 'guaranteed'. Re-author the question / workspace / news input to remove the offending phrase.` |

The builder refused to produce a prompt for the tainted input — contract upheld.

---

## 7. Rules-Presence Validation

For every case in §6, the harness asserted each of the following independently:

- `SYSTEM_RULES` — **9 / 9** rules present in the assembled prompt.
- `RESPONSE_CONSTRAINTS_ALLOWED` — **4 / 4** allowed tokens present.
- `RESPONSE_CONSTRAINTS_FORBIDDEN` — **5 / 5** forbidden-behaviour labels present in the constraints section.
- Fallback reply string — present.
- `[DD:MM:YY HH:MM:SS]` header — embedded in the OBSERVABLE MARKET DATA block.

No missing rule was reported for any case (`missing_rules: []` for all four).

---

## 8. Forbidden-Content Validation

Across all four live cases, **zero** of the 14 forbidden phrases were detected in caller-supplied content:

```
guaranteed: false   smart money: false   accumulation: false   distribution: false
buy signal: false   sell signal: false   target price: false   stop loss: false
should buy: false   should sell: false   will rally: false     will crash: false
is bullish: false   is bearish: false
```

Note: the *constraint section* legitimately names some of these labels (e.g. `guaranteed movement statements`) — the scan is correctly scoped to user inputs only, so legitimate constraint emission does not produce a false positive.

---

## 9. Timestamp Validation

`build_llm_prompt` stamps each payload with the build time formatted as
`DD:MM:YY HH:MM:SS`. The same timestamp is also embedded in the OBSERVABLE
MARKET DATA section header.

All four live cases produced timestamps that match the regex
`^\d{2}:\d{2}:\d{2} \d{2}:\d{2}:\d{2}$`:

```
25:05:26 12:51:14
25:05:26 12:51:15
25:05:26 12:51:16
25:05:26 12:51:16
```

---

## 10. Test & Lint Results

```
pytest MM.AI/tests -q                                  →  102 passed, 0 failed
        (26 LLM prompt-builder tests + 76 previously-passing tests)
python tests/_llm_prompt_validation_run.py             →  exit 0
ReadLints (llm_models, llm_prompt_builder,
           test_llm_prompt_builder, validation runner)  →  no errors
```

---

## 11. Warnings / Errors

- None during live validation.
- The forbidden-phrase guard is intentionally scoped to caller-supplied content. The constraints section embeds those same labels as forbidden-behaviour names so the future LLM is told what to avoid; scoping prevents the guard from rejecting its own prompt scaffold.
- `workspace_html` is accepted in the public signature for API symmetry with the workspace pipeline but is never rendered into `prompt_text`. Callers who only have HTML must obtain plain text separately (e.g. via `format_observations()` or `QTextBrowser.toPlainText()`).
- Article bodies, sentiment scores, sector classifications, market-impact labels, or any other speculative field would all be discarded silently if a dict-shaped news input carried them — the normaliser only retains `source`, `headline`, `url`, `timestamp`.
- The builder never imports, references, or initialises any LLM SDK. It depends only on `src.news_models` (dataclasses) and `src.llm_models` (constants). No network call is made.
