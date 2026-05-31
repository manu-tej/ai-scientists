"""Tests for the provider abstraction + agnostic agent loop (no network)."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.providers import (
    ToolCall, TurnResult, FakeProvider, GeminiProvider,
    _normalize_gemini_stop, make_provider,
)
from scripts.agent import run_agent_loop


# ---- contract + loop ---- #

def test_fakeprovider_scripts_turns():
    fake = FakeProvider(scripted=[
        TurnResult(["t"], [ToolCall("t1", "print(1)")], "tool_use", 10, 5, 0, 0),
        TurnResult(["done"], [], "end_turn", 8, 4, 0, 0),
    ])
    fake.add_user_text("instruction")
    assert fake.advance().stop_reason == "tool_use"
    fake.add_tool_results([("t1", "STDOUT:\n1", False)])
    assert fake.advance().stop_reason == "end_turn"
    assert fake.tool_results_seen == [[("t1", "STDOUT:\n1", False)]]


def test_loop_writes_artifacts_and_meta(tmp_path: Path):
    sandbox = tmp_path / "run"; sandbox.mkdir()
    code = "open('trace.md','w').write('# t'); open('answer.txt','w').write('ANSWER: yes')"
    fake = FakeProvider(scripted=[
        TurnResult(["working"], [ToolCall("tc1", code)], "tool_use", 100, 20, 0, 0),
        TurnResult(["done"], [], "end_turn", 50, 10, 0, 0),
    ])
    meta = run_agent_loop(fake, sandbox=sandbox, max_turns=5)
    assert (sandbox / "trace.md").exists() and (sandbox / "answer.txt").exists()
    assert meta["turns_used"] == 2 and meta["stop_reason"] == "end_turn"
    assert meta["tokens"]["input_total"] == 150 and meta["tokens"]["output_total"] == 30
    logged = list((sandbox / "_tool_calls").glob("turn_*.py"))
    assert len(logged) == 1 and "trace.md" in logged[0].read_text()


def test_loop_recovers_from_max_tokens(tmp_path: Path):
    sandbox = tmp_path / "run"; sandbox.mkdir()
    good = "open('trace.md','w').write('t'); open('answer.txt','w').write('a')"
    fake = FakeProvider(scripted=[
        TurnResult(["cut"], [ToolCall("t1", "partial")], "max_tokens", 10, 8192, 0, 0),
        TurnResult(["retry"], [ToolCall("t2", good)], "tool_use", 20, 30, 0, 0),
        TurnResult(["done"], [], "end_turn", 5, 5, 0, 0),
    ])
    meta = run_agent_loop(fake, sandbox=sandbox, max_turns=5)
    assert any("cut off" in t for t in fake.user_texts)
    assert meta["produced_answer"] is True


# ---- gemini normalization (no network) ---- #

def test_normalize_stop_reasons():
    assert _normalize_gemini_stop("STOP", True) == "tool_use"
    assert _normalize_gemini_stop("STOP", False) == "end_turn"
    assert _normalize_gemini_stop("MAX_TOKENS", False) == "max_tokens"
    assert _normalize_gemini_stop("SAFETY", False) == "SAFETY"
    # enum-repr form (what the SDK actually returns)
    assert _normalize_gemini_stop("FinishReason.STOP", False) == "end_turn"
    assert _normalize_gemini_stop("FinishReason.MAX_TOKENS", True) == "max_tokens"


def test_gemini_parse_response():
    fc = SimpleNamespace(id="call_1", name="run_python", args={"code": "print(1)"})
    cand = SimpleNamespace(
        content=SimpleNamespace(parts=[SimpleNamespace(text="reasoning", function_call=None),
                                       SimpleNamespace(text=None, function_call=fc)]),
        finish_reason="STOP")
    resp = SimpleNamespace(candidates=[cand],
                           usage_metadata=SimpleNamespace(prompt_token_count=123,
                                                          candidates_token_count=45,
                                                          cached_content_token_count=0))
    tr = GeminiProvider._parse_response(resp)
    assert tr.stop_reason == "tool_use" and tr.text_blocks == ["reasoning"]
    assert tr.tool_calls[0].code == "print(1)" and tr.in_tokens == 123


# ---- routing ---- #

def test_routes_by_prefix(monkeypatch):
    import scripts.providers as P
    chosen = {}
    monkeypatch.setattr(P, "AnthropicProvider", lambda *a, **k: chosen.setdefault("p", "anthropic"))
    monkeypatch.setattr(P, "GeminiProvider", lambda *a, **k: chosen.setdefault("p", "gemini"))
    make_provider("claude-opus-4-7", "sys"); assert chosen["p"] == "anthropic"
    chosen.clear()
    make_provider("gemini-3.1-pro-preview", "sys"); assert chosen["p"] == "gemini"


def test_unknown_model_raises():
    with pytest.raises(ValueError, match="Unknown model"):
        make_provider("llama-3", "sys")
