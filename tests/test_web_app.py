"""Tests for the headless MM.AI web app helpers."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import web_app  # noqa: E402
from src.news_models import NewsResult  # noqa: E402


def test_load_workspace_updates_state(monkeypatch):
    state = web_app.WebState()

    def fake_pipeline(symbols, *, lookback, news_limit, news_timeout):
        assert symbols == ["RELIANCE", "INFY"]
        assert lookback == 3
        assert news_limit == 2
        return (
            "<p>obs</p>",
            "<p>news</p>",
            [
                NewsResult(
                    symbol="RELIANCE",
                    timestamp="13:06:26 10:00:00",
                    count=0,
                )
            ],
        )

    monkeypatch.setattr(web_app, "run_pipeline", fake_pipeline)
    monkeypatch.setattr(web_app, "_workspace_text_for_symbols", lambda s, l: "workspace")

    out = web_app.load_workspace(
        {"symbols": "reliance, infy", "lookback": 3, "news_limit": 2}, state
    )

    assert out["ok"] is True
    assert out["symbols"] == ["RELIANCE", "INFY"]
    assert out["observation_html"] == "<p>obs</p>"
    assert state.workspace_text == "workspace"


def test_ask_question_autoloads_when_symbols_supplied(monkeypatch):
    state = web_app.WebState()

    monkeypatch.setattr(
        web_app,
        "run_pipeline",
        lambda *_a, **_kw: ("<p>obs</p>", "<p>news</p>", []),
    )
    monkeypatch.setattr(web_app, "_workspace_text_for_symbols", lambda s, l: "SYMBOL: RELIANCE")

    class FakeResponse:
        ok = True
        timestamp = "13:06:26 10:00:00"
        response_text = "OK"
        error = None

    def fake_prompt(**kwargs):
        assert kwargs["user_question"] == "Say OK"
        assert kwargs["symbols"] == ["RELIANCE"]
        return object()

    monkeypatch.setattr(web_app, "build_llm_prompt", fake_prompt)
    monkeypatch.setattr(web_app, "generate_llm_response", lambda *_a, **_kw: FakeResponse())
    monkeypatch.setattr(web_app, "load_config_from_env", lambda: object())

    out = web_app.ask_question({"symbols": "RELIANCE", "question": "Say OK"}, state)

    assert out == {
        "ok": True,
        "kind": "ok",
        "timestamp": "13:06:26 10:00:00",
        "response_text": "OK",
        "symbols": ["RELIANCE"],
    }
