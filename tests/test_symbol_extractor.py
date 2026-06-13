"""Unit tests for :mod:`src.symbol_extractor`.

Covers:

- Lowercase / mixed-case input.
- Comma + semicolon + whitespace separators.
- Punctuation stripping (``?`` ``.`` ``!`` etc.).
- Order preservation + deduplication.
- Stop-word guard (common English words never match).
- Safe-fallback corpus when ``known_symbols`` is omitted.
- Membership filter when ``known_symbols`` is supplied.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.symbol_extractor import (
    SAFE_FALLBACK_SYMBOLS,
    extract_symbols_from_question,
)


# ---------------------------------------------------------------------------
# Spec validation cases (1..6)
# ---------------------------------------------------------------------------


def test_case_1_compare_nifty_and_reliance():
    assert extract_symbols_from_question("compare nifty and reliance") == [
        "NIFTY",
        "RELIANCE",
    ]


def test_case_2_what_changed_in_reliance_today():
    assert extract_symbols_from_question("What changed in RELIANCE today?") == [
        "RELIANCE"
    ]


def test_case_3_show_infy_activity():
    assert extract_symbols_from_question("Show INFY activity") == ["INFY"]


def test_case_4_why_is_nifty_in_news():
    assert extract_symbols_from_question("Why is NIFTY in news?") == ["NIFTY"]


def test_case_5_compare_reliance_infy_and_nifty():
    assert extract_symbols_from_question(
        "compare reliance, infy and nifty"
    ) == ["RELIANCE", "INFY", "NIFTY"]


def test_case_6_what_changed_today_has_no_symbols():
    assert extract_symbols_from_question("what changed today?") == []


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------


def test_empty_and_none_inputs_return_empty():
    assert extract_symbols_from_question("") == []
    assert extract_symbols_from_question(None) == []
    assert extract_symbols_from_question("   \t\n   ") == []


def test_lowercase_input_is_upper_cased():
    assert extract_symbols_from_question("nifty") == ["NIFTY"]
    assert extract_symbols_from_question("Reliance Infy") == ["RELIANCE", "INFY"]


def test_punctuation_is_stripped():
    assert extract_symbols_from_question("RELIANCE!!!") == ["RELIANCE"]
    assert extract_symbols_from_question("(NIFTY)") == ["NIFTY"]
    assert extract_symbols_from_question("INFY.") == ["INFY"]


def test_question_marks_and_quotes_dont_break_extraction():
    assert extract_symbols_from_question("'INFY'?") == ["INFY"]
    assert extract_symbols_from_question('"NIFTY" today') == ["NIFTY"]


# ---------------------------------------------------------------------------
# Separators
# ---------------------------------------------------------------------------


def test_comma_separated_symbols():
    assert extract_symbols_from_question("reliance,infy,nifty") == [
        "RELIANCE",
        "INFY",
        "NIFTY",
    ]


def test_semicolon_separated_symbols():
    assert extract_symbols_from_question("reliance;infy;nifty") == [
        "RELIANCE",
        "INFY",
        "NIFTY",
    ]


def test_mixed_separators():
    assert extract_symbols_from_question(
        "reliance, infy; and nifty"
    ) == ["RELIANCE", "INFY", "NIFTY"]


# ---------------------------------------------------------------------------
# Order + dedup
# ---------------------------------------------------------------------------


def test_order_is_preserved_by_first_occurrence():
    assert extract_symbols_from_question("nifty reliance infy") == [
        "NIFTY",
        "RELIANCE",
        "INFY",
    ]
    assert extract_symbols_from_question("infy reliance nifty") == [
        "INFY",
        "RELIANCE",
        "NIFTY",
    ]


def test_duplicates_are_collapsed():
    assert extract_symbols_from_question(
        "reliance reliance and RELIANCE"
    ) == ["RELIANCE"]


def test_duplicates_preserved_first_occurrence():
    assert extract_symbols_from_question(
        "nifty reliance nifty infy reliance"
    ) == ["NIFTY", "RELIANCE", "INFY"]


# ---------------------------------------------------------------------------
# Stop-word guard
# ---------------------------------------------------------------------------


def test_normal_english_words_are_not_symbols():
    # All of the words below should be ignored even if a rare ticker collides.
    cases = [
        "what is the price today",
        "show me the market activity",
        "compare yesterday and today",
        "tell me about price changes",
        "any news today?",
    ]
    for q in cases:
        assert extract_symbols_from_question(q) == [], q


def test_stop_words_dont_match_even_with_known_symbols_list():
    # Even if a stop-word happens to be present in the catalogue, the guard
    # keeps it out of the extracted list.
    known = ["NIFTY", "RELIANCE", "WHAT", "TODAY"]
    assert extract_symbols_from_question(
        "what changed in reliance today?", known_symbols=known
    ) == ["RELIANCE"]


# ---------------------------------------------------------------------------
# Safe fallback corpus (no known_symbols supplied)
# ---------------------------------------------------------------------------


def test_safe_fallback_corpus_contents():
    assert SAFE_FALLBACK_SYMBOLS == frozenset(
        {"NIFTY", "BANKNIFTY", "RELIANCE", "INFY"}
    )


def test_unknown_tokens_are_not_invented_under_fallback():
    # ZZZZ is not in the safe fallback set; the extractor must NOT invent it.
    assert extract_symbols_from_question("ZZZZ ZZZZ") == []
    assert extract_symbols_from_question("buy tcs") == []  # TCS not in fallback


def test_banknifty_is_extracted_under_fallback():
    assert extract_symbols_from_question("banknifty open today") == ["BANKNIFTY"]


# ---------------------------------------------------------------------------
# Membership filter when known_symbols is supplied
# ---------------------------------------------------------------------------


def test_known_symbols_filter_expands_universe():
    # TCS is not in the safe fallback set but is in the supplied catalogue.
    assert extract_symbols_from_question(
        "show tcs", known_symbols=["TCS", "INFY"]
    ) == ["TCS"]


def test_known_symbols_filter_restricts_to_catalogue():
    # RELIANCE is not in this restricted catalogue, so it must not be returned.
    assert extract_symbols_from_question(
        "compare reliance and tcs", known_symbols=["TCS"]
    ) == ["TCS"]


def test_empty_known_symbols_falls_back_to_safe_corpus():
    assert extract_symbols_from_question(
        "nifty reliance tcs", known_symbols=[]
    ) == ["NIFTY", "RELIANCE"]


def test_known_symbols_none_uses_safe_fallback():
    assert extract_symbols_from_question(
        "nifty reliance tcs", known_symbols=None
    ) == ["NIFTY", "RELIANCE"]


def test_known_symbols_handles_garbage_entries():
    # Non-string entries and blank strings must be skipped without raising.
    assert extract_symbols_from_question(
        "tcs and infy",
        known_symbols=["TCS", "", None, 123, "INFY"],
    ) == ["TCS", "INFY"]
