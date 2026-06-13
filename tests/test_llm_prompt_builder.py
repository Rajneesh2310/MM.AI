"""Tests for the MM.AI safe LLM prompt builder.

Validates:
- All five sections are present and ordered.
- Every immutable SYSTEM_RULE appears in the rendered prompt.
- Every RESPONSE_CONSTRAINTS_ALLOWED token appears.
- Every RESPONSE_CONSTRAINTS_FORBIDDEN token appears (so the LLM is told
  what NOT to do — these are emitted as forbidden behaviours, never as
  output of the assistant).
- Forbidden output phrases never leak through user inputs.
- Workspace text is sanitised (file paths, parquet refs, tracebacks,
  exception markers, dataframe reprs).
- News list accepts ``NewsItem``, ``NewsResult``, and plain dicts; only the
  four canonical fields end up in the prompt.
- Timestamp matches DD:MM:YY HH:MM:SS.
- The four validation questions all produce well-formed payloads.
- Empty / None inputs degrade gracefully without crashing.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest

from src.llm_models import (
    FORBIDDEN_OUTPUT_PHRASES,
    LLMPromptPayload,
    MAX_QUESTION_CHARS,
    RESPONSE_CONSTRAINTS_ALLOWED,
    RESPONSE_CONSTRAINTS_FORBIDDEN,
    SYSTEM_RULES,
)
from src.llm_prompt_builder import build_llm_prompt
from src.news_models import NewsItem, NewsResult

TIMESTAMP_RE = re.compile(r"^\d{2}:\d{2}:\d{2} \d{2}:\d{2}:\d{2}$")


SAMPLE_WORKSPACE_TEXT = (
    "[25:05:26 12:00:00]\n"
    "\n"
    "SYMBOL: RELIANCE\n"
    "\n"
    "CASH\n"
    "\n"
    "Latest Session:\n"
    "2026-05-20\n"
    "\n"
    "Latest Close:\n"
    "1359.7\n"
    "\n"
    "Close Delta:\n"
    "37.0\n"
    "\n"
    "F&O\n"
    "\n"
    "Latest OI Total:\n"
    "118900500.0\n"
)


def _populated_news(symbol: str = "RELIANCE") -> NewsResult:
    ts = "25:05:26 12:00:01"
    return NewsResult(
        symbol=symbol,
        timestamp=ts,
        count=2,
        items=[
            NewsItem(
                headline=f"{symbol} hits new monthly high",
                source="Wire24",
                url=f"https://news.example/{symbol.lower()}-high",
                timestamp=ts,
            ),
            NewsItem(
                headline=f"Quarterly results published for {symbol}",
                source="MarketDesk",
                url=f"https://news.example/{symbol.lower()}-q",
                timestamp=ts,
            ),
        ],
    )


# ---------------------------------------------------------------------------
# Section structure
# ---------------------------------------------------------------------------


def test_payload_has_all_five_sections_in_order():
    payload = build_llm_prompt(
        "What changed in RELIANCE today?",
        workspace_html="<div>ignored</div>",
        workspace_text=SAMPLE_WORKSPACE_TEXT,
        news_items=[_populated_news("RELIANCE")],
        symbols=["RELIANCE"],
    )
    pt = payload.prompt_text
    # Section headers are sandwiched between two "===…===" rule lines, so we
    # search for the rule + header pattern to disambiguate from in-body
    # references to the same labels (e.g. SYSTEM RULES mentions OBSERVABLE
    # MARKET DATA / NEWS HEADLINES in its instructional text).
    headers = [
        "SYSTEM RULES",
        "USER QUESTION",
        "OBSERVABLE MARKET DATA",
        "NEWS HEADLINES",
        "RESPONSE CONSTRAINTS",
    ]
    positions = []
    for header in headers:
        pattern = re.compile(rf"={{60}}\n{re.escape(header)}\n={{60}}")
        match = pattern.search(pt)
        assert match is not None, f"missing section header: {header}"
        positions.append(match.start())
    assert positions == sorted(positions)


def test_payload_dict_shape():
    payload = build_llm_prompt(
        "Compare RELIANCE and INFY.",
        workspace_html=None,
        workspace_text=SAMPLE_WORKSPACE_TEXT,
        news_items=[],
        symbols=["RELIANCE", "INFY"],
    )
    assert isinstance(payload, LLMPromptPayload)
    d = payload.as_dict()
    assert set(d.keys()) == {"timestamp", "symbols", "question", "prompt_text"}
    assert d["symbols"] == ["RELIANCE", "INFY"]
    assert d["question"] == "Compare RELIANCE and INFY."
    assert isinstance(d["prompt_text"], str) and d["prompt_text"]


def test_timestamp_format():
    payload = build_llm_prompt(
        "What changed?",
        None,
        SAMPLE_WORKSPACE_TEXT,
        None,
        ["RELIANCE"],
    )
    assert TIMESTAMP_RE.match(payload.timestamp), payload.timestamp
    # Same timestamp string is embedded in the OBSERVABLE MARKET DATA section.
    assert payload.timestamp in payload.prompt_text


# ---------------------------------------------------------------------------
# Rule presence
# ---------------------------------------------------------------------------


def test_every_system_rule_is_present():
    payload = build_llm_prompt(
        "Show INFY activity.",
        None,
        SAMPLE_WORKSPACE_TEXT,
        [_populated_news("INFY")],
        ["INFY"],
    )
    for rule in SYSTEM_RULES:
        assert rule in payload.prompt_text, f"missing immutable rule: {rule!r}"


def test_response_constraints_allowed_and_forbidden_lists_present():
    payload = build_llm_prompt(
        "Why is NIFTY in news?",
        None,
        SAMPLE_WORKSPACE_TEXT,
        [_populated_news("NIFTY")],
        ["NIFTY"],
    )
    for token in RESPONSE_CONSTRAINTS_ALLOWED:
        assert token in payload.prompt_text
    for token in RESPONSE_CONSTRAINTS_FORBIDDEN:
        assert token in payload.prompt_text


def test_fallback_answer_string_is_quoted_verbatim():
    payload = build_llm_prompt(
        "Anything?",
        None,
        SAMPLE_WORKSPACE_TEXT,
        [],
        ["RELIANCE"],
    )
    assert (
        '"I do not have enough observable data to answer that."'
        in payload.prompt_text
    )


# ---------------------------------------------------------------------------
# Forbidden-phrase guard
# ---------------------------------------------------------------------------


def test_forbidden_phrase_in_question_raises():
    """Caller-supplied content must not slip into the prompt unchanged."""
    bad_question = "Give me a guaranteed buy signal for RELIANCE."
    with pytest.raises(ValueError) as exc:
        build_llm_prompt(
            bad_question,
            None,
            SAMPLE_WORKSPACE_TEXT,
            [],
            ["RELIANCE"],
        )
    assert "forbidden" in str(exc.value).lower()


def test_forbidden_phrase_in_workspace_text_raises():
    bad_workspace = SAMPLE_WORKSPACE_TEXT + "\n\nSignal: should buy now."
    with pytest.raises(ValueError):
        build_llm_prompt(
            "Show me",
            None,
            bad_workspace,
            [],
            ["RELIANCE"],
        )


def test_clean_inputs_do_not_trip_forbidden_guard():
    """Clean caller inputs must not raise; the constraints section may
    *legitimately* name forbidden behaviours by label (those labels appear
    in the assembled prompt to instruct the LLM what to avoid)."""
    payload = build_llm_prompt(
        "What changed in RELIANCE today?",
        None,
        SAMPLE_WORKSPACE_TEXT,
        [_populated_news("RELIANCE")],
        ["RELIANCE"],
    )
    # User-supplied content must not contain forbidden phrases — the
    # constraints section is exempt as it names them as forbidden behaviours.
    assert payload.question == "What changed in RELIANCE today?"


# ---------------------------------------------------------------------------
# Workspace sanitisation
# ---------------------------------------------------------------------------


def test_parquet_paths_are_stripped():
    tainted = (
        SAMPLE_WORKSPACE_TEXT
        + '\nLoaded from C:\\Users\\DELL\\MMMarket\\data\\cash\\SYMBOL=RELIANCE\\YEAR=2026.parquet'
    )
    payload = build_llm_prompt(
        "show", None, tainted, [], ["RELIANCE"]
    )
    assert ".parquet" not in payload.prompt_text
    assert "MMMarket" not in payload.prompt_text
    assert "C:\\Users" not in payload.prompt_text


def test_traceback_block_is_stripped():
    tainted = (
        SAMPLE_WORKSPACE_TEXT
        + "\nTraceback (most recent call last):\n"
        + '  File "src/symbol_reader.py", line 99, in load_symbol_data\n'
        + "    return _build_cash(sym, lookback)\n"
        + "ValueError: symbol required\n"
    )
    payload = build_llm_prompt("show", None, tainted, [], ["RELIANCE"])
    assert "Traceback" not in payload.prompt_text
    assert "File \"" not in payload.prompt_text
    assert "ValueError: symbol required" not in payload.prompt_text


def test_dataframe_repr_is_stripped():
    tainted = SAMPLE_WORKSPACE_TEXT + "\nshape: (244, 16) <DataFrame ...>"
    payload = build_llm_prompt("show", None, tainted, [], ["RELIANCE"])
    assert "shape:" not in payload.prompt_text
    assert "<DataFrame" not in payload.prompt_text


def test_control_chars_are_stripped_from_question_and_workspace():
    payload = build_llm_prompt(
        "What\x00 changed\x07?",
        None,
        SAMPLE_WORKSPACE_TEXT + "\nbad\x00data\x07line",
        [],
        ["RELIANCE"],
    )
    assert "\x00" not in payload.prompt_text
    assert "\x07" not in payload.prompt_text


def test_workspace_html_is_not_leaked_into_prompt():
    payload = build_llm_prompt(
        "show",
        workspace_html="<table><tr><td>secret-html</td></tr></table>",
        workspace_text=SAMPLE_WORKSPACE_TEXT,
        news_items=None,
        symbols=["RELIANCE"],
    )
    assert "secret-html" not in payload.prompt_text
    assert "<table" not in payload.prompt_text


# ---------------------------------------------------------------------------
# Question / symbols input validation
# ---------------------------------------------------------------------------


def test_question_is_length_capped():
    long_q = "A" * (MAX_QUESTION_CHARS + 100)
    payload = build_llm_prompt(long_q, None, SAMPLE_WORKSPACE_TEXT, [], ["RELIANCE"])
    assert len(payload.question) == MAX_QUESTION_CHARS
    assert payload.question in payload.prompt_text


def test_symbols_are_uppercased_and_deduped():
    payload = build_llm_prompt(
        "show",
        None,
        SAMPLE_WORKSPACE_TEXT,
        [],
        ["reliance", "RELIANCE", "infy"],
    )
    assert payload.symbols == ("RELIANCE", "INFY")


def test_empty_inputs_do_not_crash():
    payload = build_llm_prompt("", None, None, None, None)
    assert payload.question == ""
    assert payload.symbols == ()
    assert "(no question provided)" in payload.prompt_text
    assert "(no observable workspace data available)" in payload.prompt_text
    assert "(no news headlines available)" in payload.prompt_text


# ---------------------------------------------------------------------------
# News item handling
# ---------------------------------------------------------------------------


def test_news_accepts_news_item_list():
    items = _populated_news().items
    payload = build_llm_prompt("show", None, SAMPLE_WORKSPACE_TEXT, items, ["RELIANCE"])
    for it in items:
        assert it.headline in payload.prompt_text
        assert it.url in payload.prompt_text
        assert (it.source or "Not Available") in payload.prompt_text


def test_news_accepts_news_result_and_flattens():
    payload = build_llm_prompt(
        "show",
        None,
        SAMPLE_WORKSPACE_TEXT,
        [_populated_news("RELIANCE"), _populated_news("INFY")],
        ["RELIANCE", "INFY"],
    )
    assert "Total headline references: 4" in payload.prompt_text


def test_news_accepts_plain_dicts():
    items = [
        {
            "source": "Wire24",
            "headline": "ACME launches new product",
            "url": "https://news.example/launch",
            "timestamp": "25:05:26 12:00:00",
        }
    ]
    payload = build_llm_prompt("show", None, SAMPLE_WORKSPACE_TEXT, items, ["ACME"])
    assert "ACME launches new product" in payload.prompt_text
    assert "https://news.example/launch" in payload.prompt_text


def test_news_item_body_or_sentiment_never_leaks():
    """Extra dict keys carrying article body / sentiment must be discarded."""
    items = [
        {
            "source": "Wire24",
            "headline": "Headline only",
            "url": "https://news.example/headline",
            "timestamp": "25:05:26 12:00:00",
            "body": "FULL ARTICLE BODY THAT SHOULD NEVER APPEAR",
            "sentiment": "EXTREMELY_POSITIVE",
        }
    ]
    payload = build_llm_prompt("show", None, SAMPLE_WORKSPACE_TEXT, items, ["ACME"])
    assert "FULL ARTICLE BODY" not in payload.prompt_text
    assert "EXTREMELY_POSITIVE" not in payload.prompt_text


# ---------------------------------------------------------------------------
# Builder is pure (no side effects on input objects)
# ---------------------------------------------------------------------------


def test_builder_does_not_mutate_input_lists():
    symbols = ["RELIANCE", "INFY"]
    items = [_populated_news("RELIANCE")]
    before = (list(symbols), list(items[0].items))
    build_llm_prompt("show", None, SAMPLE_WORKSPACE_TEXT, items, symbols)
    assert symbols == before[0]
    assert list(items[0].items) == before[1]


# ---------------------------------------------------------------------------
# The four validation questions (smoke test)
# ---------------------------------------------------------------------------


VALIDATION_QUESTIONS = [
    ("What changed in RELIANCE today?", ["RELIANCE"]),
    ("Compare RELIANCE and INFY.", ["RELIANCE", "INFY"]),
    ("Why is NIFTY in news?", ["NIFTY"]),
    ("Show INFY activity.", ["INFY"]),
]


@pytest.mark.parametrize("question,symbols", VALIDATION_QUESTIONS)
def test_validation_questions_produce_valid_payloads(question, symbols):
    payload = build_llm_prompt(
        question,
        None,
        SAMPLE_WORKSPACE_TEXT,
        [_populated_news(symbols[0])],
        symbols,
    )
    assert payload.question == question
    assert tuple(symbols) == payload.symbols
    assert "SYSTEM RULES" in payload.prompt_text
    assert "USER QUESTION" in payload.prompt_text
    assert question in payload.prompt_text
    for rule in SYSTEM_RULES:
        assert rule in payload.prompt_text
    # Forbidden phrases must not appear in any caller-supplied content. The
    # constraints section legitimately names them as forbidden behaviours.
    user_supplied = (
        payload.question + "\n" + SAMPLE_WORKSPACE_TEXT
    ).lower()
    for phrase in FORBIDDEN_OUTPUT_PHRASES:
        assert phrase not in user_supplied
