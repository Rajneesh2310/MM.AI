"""Tests for MM.AI's read-only adapter over MM's existing symbol catalogue.

Covers:
- Reading from ``cash_symbols.json`` / ``fo_symbols.json`` (the canonical
  artifacts MM already maintains).
- Falling back to ``SYMBOL=*`` partition enumeration when the JSON cache
  is missing.
- Empty / malformed JSON handled silently.
- ``find_matches`` deterministic ranking: exact > prefix > contains >
  difflib similarity.
- Query sanitisation (lower-case, whitespace, punctuation outside the NSE
  symbol char set).
- ``is_known`` boolean check.
- In-memory cache is bypassed by :func:`clear_cache` (tests must isolate).
- No write to the MM tree under any code path.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import symbol_catalog


@pytest.fixture(autouse=True)
def _isolate_cache():
    symbol_catalog.clear_cache()
    yield
    symbol_catalog.clear_cache()


@pytest.fixture
def fake_install_root(tmp_path, monkeypatch):
    (tmp_path / "data").mkdir(parents=True)
    (tmp_path / "data" / "cash").mkdir()
    (tmp_path / "data" / "fo").mkdir()
    monkeypatch.setenv("MM_INSTALL_ROOT", str(tmp_path))
    return tmp_path


def _write_cache(install_root: Path, segment: str, symbols: list[str]) -> Path:
    path = install_root / "data" / f"{segment}_symbols.json"
    path.write_text(json.dumps(symbols), encoding="utf-8")
    return path


def _make_partitions(install_root: Path, segment: str, symbols: list[str]) -> None:
    base = install_root / "data" / segment
    for sym in symbols:
        (base / f"SYMBOL={sym}").mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# JSON cache path (preferred)
# ---------------------------------------------------------------------------


def test_list_cash_symbols_reads_existing_json_cache(fake_install_root):
    _write_cache(fake_install_root, "cash", ["RELIANCE", "INFY", "TCS"])
    result = symbol_catalog.list_cash_symbols()
    assert result == ("INFY", "RELIANCE", "TCS")


def test_list_fo_symbols_reads_existing_json_cache(fake_install_root):
    _write_cache(fake_install_root, "fo", ["NIFTY", "BANKNIFTY", "RELIANCE"])
    result = symbol_catalog.list_fo_symbols()
    assert result == ("BANKNIFTY", "NIFTY", "RELIANCE")


def test_list_all_symbols_is_union_of_both(fake_install_root):
    _write_cache(fake_install_root, "cash", ["RELIANCE", "INFY"])
    _write_cache(fake_install_root, "fo", ["RELIANCE", "NIFTY"])
    union = symbol_catalog.list_all_symbols()
    assert union == ("INFY", "NIFTY", "RELIANCE")  # deduplicated


def test_list_cash_symbols_uppercases_and_strips(fake_install_root):
    _write_cache(fake_install_root, "cash", ["  reliance ", "infy", "TCS\n"])
    assert symbol_catalog.list_cash_symbols() == ("INFY", "RELIANCE", "TCS")


def test_malformed_json_returns_empty(fake_install_root):
    (fake_install_root / "data" / "cash_symbols.json").write_text(
        "this is not json", encoding="utf-8"
    )
    assert symbol_catalog.list_cash_symbols() == ()


def test_non_list_json_returns_empty(fake_install_root):
    (fake_install_root / "data" / "cash_symbols.json").write_text(
        json.dumps({"symbols": ["RELIANCE"]}), encoding="utf-8"
    )
    assert symbol_catalog.list_cash_symbols() == ()


def test_non_string_entries_dropped(fake_install_root):
    _write_cache(
        fake_install_root, "cash", ["RELIANCE", "", None, 123, "INFY"]
    )  # type: ignore[list-item]
    assert symbol_catalog.list_cash_symbols() == ("INFY", "RELIANCE")


# ---------------------------------------------------------------------------
# Partition fallback (used only when JSON missing)
# ---------------------------------------------------------------------------


def test_partition_fallback_when_json_missing(fake_install_root):
    _make_partitions(fake_install_root, "cash", ["RELIANCE", "INFY"])
    # No cash_symbols.json present.
    assert symbol_catalog.list_cash_symbols() == ("INFY", "RELIANCE")


def test_json_preferred_over_partitions(fake_install_root):
    _write_cache(fake_install_root, "cash", ["RELIANCE"])
    _make_partitions(fake_install_root, "cash", ["RELIANCE", "INFY"])
    # JSON wins — partitions are only a fallback.
    assert symbol_catalog.list_cash_symbols() == ("RELIANCE",)


def test_empty_when_nothing_exists(fake_install_root):
    assert symbol_catalog.list_cash_symbols() == ()
    assert symbol_catalog.list_fo_symbols() == ()
    assert symbol_catalog.list_all_symbols() == ()


# ---------------------------------------------------------------------------
# In-memory caching
# ---------------------------------------------------------------------------


def test_cache_is_used_across_calls(fake_install_root):
    cache_path = _write_cache(fake_install_root, "cash", ["RELIANCE", "INFY"])
    first = symbol_catalog.list_cash_symbols()
    cache_path.write_text(json.dumps(["NEWSYM"]), encoding="utf-8")
    second = symbol_catalog.list_cash_symbols()
    assert first == second == ("INFY", "RELIANCE")  # cache held


def test_clear_cache_picks_up_fresh_data(fake_install_root):
    cache_path = _write_cache(fake_install_root, "cash", ["RELIANCE"])
    assert symbol_catalog.list_cash_symbols() == ("RELIANCE",)
    cache_path.write_text(json.dumps(["INFY"]), encoding="utf-8")
    symbol_catalog.clear_cache()
    assert symbol_catalog.list_cash_symbols() == ("INFY",)


# ---------------------------------------------------------------------------
# Fuzzy matching
# ---------------------------------------------------------------------------


POOL = (
    "ADANIENT",
    "ADANIPORTS",
    "BANKNIFTY",
    "BPCL",
    "HDFCBANK",
    "ICICIBANK",
    "INFY",
    "NIFTY",
    "RELIANCE",
    "RELIANCEPP",
    "RELIGARE",
    "RELINFRA",
    "RIIL",
    "SBIN",
    "TCS",
)


def test_find_matches_exact_first():
    out = symbol_catalog.find_matches("RELIANCE", pool=POOL)
    assert out[0] == "RELIANCE"


def test_find_matches_prefix_over_contains():
    out = symbol_catalog.find_matches("REL", pool=POOL, limit=8)
    # prefix matches come before contains matches; lexical inside each bucket
    assert out.index("RELIANCE") < out.index("RELIGARE")
    assert all(s.startswith("REL") for s in out[:4])


def test_find_matches_contains_when_no_prefix():
    out = symbol_catalog.find_matches("BANK", pool=POOL)
    assert "BANKNIFTY" in out  # prefix
    assert "HDFCBANK" in out   # contains
    assert "ICICIBANK" in out  # contains
    assert out.index("BANKNIFTY") < out.index("HDFCBANK")


def test_find_matches_difflib_for_typos():
    out = symbol_catalog.find_matches("RELIANC", pool=POOL, limit=4)
    assert "RELIANCE" in out
    assert out[0] == "RELIANCE"  # prefix beats fuzzy


def test_find_matches_difflib_when_no_substring():
    out = symbol_catalog.find_matches("INPFY", pool=POOL, limit=3)
    assert "INFY" in out  # difflib catches the transposition


def test_find_matches_empty_query_returns_empty():
    assert symbol_catalog.find_matches("", pool=POOL) == []
    assert symbol_catalog.find_matches(None, pool=POOL) == []
    assert symbol_catalog.find_matches("   ", pool=POOL) == []


def test_find_matches_respects_limit():
    out = symbol_catalog.find_matches("REL", pool=POOL, limit=2)
    assert len(out) == 2


def test_find_matches_zero_or_negative_limit_returns_empty():
    assert symbol_catalog.find_matches("REL", pool=POOL, limit=0) == []
    assert symbol_catalog.find_matches("REL", pool=POOL, limit=-5) == []


def test_find_matches_uppercases_and_sanitises_query():
    out = symbol_catalog.find_matches("  rel-iance ! ", pool=POOL, limit=4)
    assert "RELIANCE" in out


def test_find_matches_handles_empty_pool():
    assert symbol_catalog.find_matches("RELIANCE", pool=()) == []


def test_find_matches_deterministic_order():
    out1 = symbol_catalog.find_matches("BANK", pool=POOL, limit=5)
    out2 = symbol_catalog.find_matches("BANK", pool=POOL, limit=5)
    out3 = symbol_catalog.find_matches("BANK", pool=POOL, limit=5)
    assert out1 == out2 == out3


# ---------------------------------------------------------------------------
# is_known + normalise_query
# ---------------------------------------------------------------------------


def test_is_known_true_for_existing_symbol(fake_install_root):
    _write_cache(fake_install_root, "cash", ["RELIANCE", "INFY"])
    assert symbol_catalog.is_known("reliance") is True
    assert symbol_catalog.is_known("  INFY  ") is True


def test_is_known_false_for_unknown_symbol(fake_install_root):
    _write_cache(fake_install_root, "cash", ["RELIANCE"])
    assert symbol_catalog.is_known("UNKNOWN_TICKER") is False
    assert symbol_catalog.is_known("") is False
    assert symbol_catalog.is_known(None) is False


def test_normalise_query_strips_disallowed_chars():
    assert symbol_catalog.normalise_query(" reliance@$%^ ") == "RELIANCE"
    assert symbol_catalog.normalise_query("ADANI-PORTS") == "ADANI-PORTS"
    assert symbol_catalog.normalise_query("M&M.NS") == "M&M.NS"


# ---------------------------------------------------------------------------
# Read-only guarantee
# ---------------------------------------------------------------------------


def test_no_files_are_written_during_lookups(fake_install_root):
    _write_cache(fake_install_root, "cash", ["RELIANCE"])
    _write_cache(fake_install_root, "fo", ["NIFTY"])

    before = sorted((fake_install_root / "data").rglob("*"))
    symbol_catalog.list_cash_symbols()
    symbol_catalog.list_fo_symbols()
    symbol_catalog.list_all_symbols()
    symbol_catalog.find_matches("RELIANCE")
    symbol_catalog.is_known("NIFTY")
    after = sorted((fake_install_root / "data").rglob("*"))

    assert before == after  # no file created, deleted or renamed
