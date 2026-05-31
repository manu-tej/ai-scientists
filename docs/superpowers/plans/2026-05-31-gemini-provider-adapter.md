# Gemini Provider Adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Gemini 3 as a second agent model behind a provider abstraction, so the existing refusal/calibration/trajectory measurements can be re-run cross-vendor without changing any downstream judge or aggregator.

**Architecture:** Extract a `Provider` interface that owns conversation state, the API call (with retry), and usage/stop-reason normalization. `scripts/agent.py`'s loop becomes provider-agnostic; it routes `claude-*` → `AnthropicProvider`, `gemini-*` → `GeminiProvider`. Every sandbox artifact the judges read (`meta.json` schema, `_tool_calls/turn_*.py`, `trace.md`, `answer.txt`) is produced by the provider-agnostic loop, so it stays identical across vendors. A test-only `FakeProvider` lets us test the loop without network.

**Tech Stack:** Python 3.13, `anthropic` SDK, `google-genai` SDK, `pytest`, `uv`.

**Scope:** This plan covers E1 (adapter) + E2 (Gemini re-runs + re-judge) + E4/E5 (2-model aggregation + RESULTS.md) from the design spec. LAB-Bench2 (E3) is a **separate** future plan.

**Key invariants that MUST be preserved (downstream code depends on them):**
- `meta.json` keys read by `trust_metrics.load_run`: `task`, `variant`, `model`, `turns_used`, `tokens.input_total`, `tokens.output_total`, `produced_trace`, `produced_answer`, `stop_reason`. (`calibration_ece` and `refusal_judge` read `judge.json` + `answer.txt`/`trace.md`, which are unaffected.)
- `_tool_calls/turn_NN_xxxxxxxx.py` files (read by `trust_metrics.tag_ops`).
- Sandbox layout `runs/agent/{task}/{model_slug}/{variant}/{ts}/` with `model_slug = model.replace(".","").replace("-","_")`.
- Stop reasons normalized to the string set `{"end_turn","tool_use","max_tokens", <other>}` so cross-provider comparisons hold.

---

### Task 1: Add dependencies and test scaffolding

**Files:**
- Modify: `pyproject.toml` (dependencies + new `[dependency-groups]` dev)
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`

- [ ] **Step 1: Add runtime + dev dependencies**

In `pyproject.toml`, add to the `dependencies` array (after `"openpyxl>=3.1.5",` and the anndata/scanpy/h5py lines):

```toml
    "google-genai>=1.33.0",
```

Add a new section after `[build-system]`:

```toml
[dependency-groups]
dev = [
    "pytest>=8.3.0",
]
```

- [ ] **Step 2: Sync and verify both SDKs import**

Run: `uv sync --group dev`
Then: `uv run python -c "import anthropic, google.genai; from google.genai import types; print('ok')"`
Expected: prints `ok`

- [ ] **Step 3: Create the tests package**

Create `tests/__init__.py` (empty file):

```python
```

Create `tests/conftest.py`:

```python
"""Shared pytest fixtures for the agent test suite."""
from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def tmp_sandbox(tmp_path: Path) -> Path:
    """A throwaway sandbox dir with a fake ./data symlink target."""
    data = tmp_path / "data_src"
    data.mkdir()
    (data / "toy.csv").write_text("a,b\n1,2\n")
    sandbox = tmp_path / "run"
    sandbox.mkdir()
    (sandbox / "data").symlink_to(data)
    return sandbox
```

- [ ] **Step 4: Verify pytest collects nothing yet (clean baseline)**

Run: `uv run pytest -q`
Expected: `no tests ran` (exit code 5) — confirms the harness is wired.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml uv.lock tests/__init__.py tests/conftest.py
git commit -m "test: add google-genai dep + pytest scaffolding"
```

---

### Task 2: Define provider contract + FakeProvider, test the loop contract

The `Provider` interface and the normalized data types are the seam. We define them with a test-only `FakeProvider` that scripts turns, then prove the contract is what the loop needs.

**Files:**
- Create: `scripts/providers.py`
- Create: `tests/test_providers_contract.py`

- [ ] **Step 1: Write the failing contract test**

Create `tests/test_providers_contract.py`:

```python
from scripts.providers import ToolCall, TurnResult, Provider, FakeProvider


def test_turnresult_fields():
    tr = TurnResult(
        text_blocks=["hi"],
        tool_calls=[ToolCall(id="t1", code="print(1)")],
        stop_reason="tool_use",
        in_tokens=10, out_tokens=5, cache_create=0, cache_read=0,
    )
    assert tr.tool_calls[0].code == "print(1)"
    assert tr.stop_reason == "tool_use"


def test_fakeprovider_scripts_turns():
    # Turn 1: one tool call. Turn 2: end_turn, no tools.
    fake = FakeProvider(scripted=[
        TurnResult(["thinking"], [ToolCall("t1", "print(1)")], "tool_use", 10, 5, 0, 0),
        TurnResult(["done"], [], "end_turn", 8, 4, 0, 0),
    ])
    fake.add_user_text("instruction")
    r1 = fake.advance()
    assert r1.stop_reason == "tool_use"
    fake.add_tool_results([("t1", "STDOUT:\n1", False)])
    r2 = fake.advance()
    assert r2.stop_reason == "end_turn"
    assert fake.tool_results_seen == [[("t1", "STDOUT:\n1", False)]]


def test_fakeprovider_drop_last_assistant():
    fake = FakeProvider(scripted=[
        TurnResult(["x"], [ToolCall("t1", "code")], "max_tokens", 1, 1, 0, 0),
        TurnResult(["y"], [], "end_turn", 1, 1, 0, 0),
    ])
    fake.advance()
    fake.drop_last_assistant()          # must not raise
    fake.add_user_text("shorter please")
    assert fake.advance().stop_reason == "end_turn"
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_providers_contract.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.providers'` (or import error).

- [ ] **Step 3: Implement the contract + FakeProvider**

Create `scripts/providers.py`:

```python
"""Provider abstraction for the agent tool-use loop.

A Provider owns the conversation history, the API call (with retry), and the
normalization of each turn into a vendor-neutral TurnResult. The agent loop in
agent.py never touches a vendor SDK directly, so every sandbox artifact it
writes is identical across providers.
"""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class ToolCall:
    id: str
    code: str


@dataclass
class TurnResult:
    text_blocks: list[str]
    tool_calls: list[ToolCall]
    stop_reason: str          # normalized: end_turn | tool_use | max_tokens | <raw>
    in_tokens: int
    out_tokens: int
    cache_create: int
    cache_read: int


# Vendor-neutral spec for the single Python tool. Each provider translates this
# into its native tool form.
RUN_PYTHON_SPEC = {
    "name": "run_python",
    "description": (
        "Execute Python code in the sandboxed working directory. Returns "
        "stdout, stderr, and the return code. Available libraries include "
        "pandas, numpy, scipy, statsmodels, scikit-learn, lifelines, openpyxl. "
        "Code runs with cwd set to the task's working directory; data files "
        "are accessible via relative paths under `./data/`."
    ),
    "parameters": {
        "type": "object",
        "properties": {"code": {"type": "string", "description": "Python code to execute."}},
        "required": ["code"],
    },
}


class Provider(ABC):
    """Owns conversation state for one agent run."""

    @abstractmethod
    def add_user_text(self, text: str) -> None:
        """Append a user-role text message (seed instruction or nudge)."""

    @abstractmethod
    def add_tool_results(self, results: list[tuple[str, str, bool]]) -> None:
        """Append tool outputs. Each tuple is (tool_call_id, content, is_error)."""

    @abstractmethod
    def advance(self) -> TurnResult:
        """Call the model with current history, append the assistant turn to
        history, and return a normalized TurnResult."""

    @abstractmethod
    def drop_last_assistant(self) -> None:
        """Remove the most recently appended assistant turn (max_tokens recovery)."""


class FakeProvider(Provider):
    """Test-only provider that replays scripted TurnResults."""

    def __init__(self, scripted: list[TurnResult]):
        self._scripted = list(scripted)
        self._i = 0
        self.user_texts: list[str] = []
        self.tool_results_seen: list[list[tuple[str, str, bool]]] = []
        self._assistant_count = 0

    def add_user_text(self, text: str) -> None:
        self.user_texts.append(text)

    def add_tool_results(self, results: list[tuple[str, str, bool]]) -> None:
        self.tool_results_seen.append(results)

    def advance(self) -> TurnResult:
        tr = self._scripted[self._i]
        self._i += 1
        self._assistant_count += 1
        return tr

    def drop_last_assistant(self) -> None:
        self._assistant_count -= 1
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_providers_contract.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add scripts/providers.py tests/test_providers_contract.py
git commit -m "feat: provider contract + FakeProvider for loop testing"
```

---

### Task 3: Extract the loop into a provider-agnostic runner, with AnthropicProvider

Refactor `agent.py` so the loop calls the `Provider` interface. Move the Anthropic-specific code into `AnthropicProvider`. Prove the loop works against `FakeProvider` by asserting sandbox artifacts.

**Files:**
- Modify: `scripts/providers.py` (add `AnthropicProvider`)
- Modify: `scripts/agent.py` (replace inline loop; add `run_agent_loop`)
- Create: `tests/test_agent_loop.py`

- [ ] **Step 1: Write the failing loop test**

Create `tests/test_agent_loop.py`:

```python
import json
from pathlib import Path

from scripts.providers import FakeProvider, TurnResult, ToolCall
from scripts.agent import run_agent_loop


def test_loop_writes_artifacts_and_meta(tmp_sandbox: Path):
    # Turn 1: a tool call that writes the two required files. Turn 2: end_turn.
    code = (
        "open('trace.md','w').write('# trace'); "
        "open('answer.txt','w').write('ANSWER: yes')"
    )
    fake = FakeProvider(scripted=[
        TurnResult(["working"], [ToolCall("tc1", code)], "tool_use", 100, 20, 0, 0),
        TurnResult(["all done"], [], "end_turn", 50, 10, 0, 0),
    ])
    meta = run_agent_loop(fake, sandbox=tmp_sandbox, max_turns=5)

    assert (tmp_sandbox / "trace.md").exists()
    assert (tmp_sandbox / "answer.txt").exists()
    assert meta["turns_used"] == 2
    assert meta["stop_reason"] == "end_turn"
    assert meta["tokens"]["input_total"] == 150
    assert meta["tokens"]["output_total"] == 30
    assert meta["produced_trace"] is True
    assert meta["produced_answer"] is True
    # tool-call code is logged for trajectory tagging
    logged = list((tmp_sandbox / "_tool_calls").glob("turn_*.py"))
    assert len(logged) == 1
    assert "trace.md" in logged[0].read_text()


def test_loop_recovers_from_max_tokens(tmp_sandbox: Path):
    good = "open('trace.md','w').write('t'); open('answer.txt','w').write('a')"
    fake = FakeProvider(scripted=[
        TurnResult(["cut"], [ToolCall("t1", "partial")], "max_tokens", 10, 8192, 0, 0),
        TurnResult(["retry"], [ToolCall("t2", good)], "tool_use", 20, 30, 0, 0),
        TurnResult(["done"], [], "end_turn", 5, 5, 0, 0),
    ])
    meta = run_agent_loop(fake, sandbox=tmp_sandbox, max_turns=5)
    # The malformed turn was dropped and a nudge was added.
    assert any("cut off" in t for t in fake.user_texts)
    assert meta["produced_answer"] is True
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_agent_loop.py -q`
Expected: FAIL with `ImportError: cannot import name 'run_agent_loop'`.

- [ ] **Step 3: Add `run_agent_loop` to agent.py**

In `scripts/agent.py`, add this function above `main()` (after `format_tool_result`). It is the provider-agnostic extraction of the current `for turn` loop:

```python
def run_agent_loop(provider, sandbox: Path, max_turns: int, console=None) -> dict:
    """Drive a Provider to completion, writing sandbox artifacts. Returns meta dict.

    Provider-agnostic: every artifact (trace.md/answer.txt are written by the
    agent's own tool calls; _tool_calls/*.py + meta.json are written here) is
    identical regardless of vendor.
    """
    total_in = total_out = total_cc = total_cr = 0
    transcript = []
    for turn in range(1, max_turns + 1):
        r = provider.advance()
        total_in += r.in_tokens
        total_out += r.out_tokens
        total_cc += r.cache_create
        total_cr += r.cache_read
        if console:
            for t in r.text_blocks:
                console.print(f"[dim]  turn {turn}:[/] {t.strip()[:120]}")
        transcript.append({"turn": turn, "stop_reason": r.stop_reason,
                           "in_tokens": r.in_tokens, "out_tokens": r.out_tokens})

        if r.stop_reason == "end_turn":
            break
        if r.stop_reason == "max_tokens" and r.tool_calls:
            provider.drop_last_assistant()
            provider.add_user_text("Your previous response was cut off. Please "
                                   "continue with a SHORTER tool call (just the next "
                                   "focused step, not multiple operations bundled).")
            continue
        if r.stop_reason != "tool_use" or not r.tool_calls:
            break

        tc_dir = sandbox / "_tool_calls"
        tc_dir.mkdir(exist_ok=True)
        results = []
        for tc in r.tool_calls:
            (tc_dir / f"turn_{turn:02d}_{tc.id[-8:]}.py").write_text(tc.code)
            out = run_python(tc.code, sandbox)
            content = format_tool_result(out)
            (tc_dir / f"turn_{turn:02d}_{tc.id[-8:]}.out").write_text(content)
            results.append((tc.id, content, out["returncode"] != 0))
        provider.add_tool_results(results)
    else:
        if console:
            console.print(f"[red]  hit max_turns ({max_turns})[/]")

    return {
        "turns_used": len(transcript),
        "stop_reason": transcript[-1]["stop_reason"] if transcript else None,
        "tokens": {"input_total": total_in, "output_total": total_out,
                   "cache_creation_total": total_cc, "cache_read_total": total_cr},
        "produced_trace": (sandbox / "trace.md").exists(),
        "produced_answer": (sandbox / "answer.txt").exists(),
        "_transcript": transcript,
    }
```

- [ ] **Step 4: Run the loop test (passes before touching main)**

Run: `uv run pytest tests/test_agent_loop.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Implement AnthropicProvider in providers.py**

Append to `scripts/providers.py`:

```python
class AnthropicProvider(Provider):
    """Anthropic Messages API with ephemeral prompt caching on the fixed prefix."""

    def __init__(self, model: str, system_text: str, max_tokens: int = 8192):
        from anthropic import Anthropic
        self._client = Anthropic()
        self._model = model
        self._max_tokens = max_tokens
        self._system = [{"type": "text", "text": system_text,
                         "cache_control": {"type": "ephemeral"}}]
        self._tools = [{
            "name": RUN_PYTHON_SPEC["name"],
            "description": RUN_PYTHON_SPEC["description"],
            "input_schema": RUN_PYTHON_SPEC["parameters"],
            "cache_control": {"type": "ephemeral"},
        }]
        self._messages: list[dict] = []
        self._first_user = True

    def add_user_text(self, text: str) -> None:
        block = {"type": "text", "text": text}
        if self._first_user:
            block["cache_control"] = {"type": "ephemeral"}
            self._first_user = False
        self._messages.append({"role": "user", "content": [block]})

    def add_tool_results(self, results):
        self._messages.append({"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": tid, "content": content, "is_error": err}
            for (tid, content, err) in results
        ]})

    def advance(self) -> TurnResult:
        from anthropic import RateLimitError, APIStatusError
        backoff = 8.0
        attempts = 0
        while True:
            try:
                resp = self._client.messages.create(
                    model=self._model, max_tokens=self._max_tokens,
                    system=self._system, tools=self._tools, messages=self._messages,
                )
                break
            except (RateLimitError, APIStatusError) as e:
                attempts += 1
                code = getattr(e, "status_code", None)
                if code is not None and code not in (429, 503, 529) and not isinstance(e, RateLimitError):
                    raise
                if attempts > 6:
                    raise
                time.sleep(backoff)
                backoff = min(backoff * 1.8, 60.0)
        self._messages.append({"role": "assistant", "content": resp.content})
        texts, calls = [], []
        for b in resp.content:
            if b.type == "text":
                texts.append(b.text)
            elif b.type == "tool_use":
                calls.append(ToolCall(id=b.id, code=b.input.get("code", "")))
        return TurnResult(
            text_blocks=texts, tool_calls=calls, stop_reason=resp.stop_reason,
            in_tokens=resp.usage.input_tokens, out_tokens=resp.usage.output_tokens,
            cache_create=getattr(resp.usage, "cache_creation_input_tokens", 0) or 0,
            cache_read=getattr(resp.usage, "cache_read_input_tokens", 0) or 0,
        )

    def drop_last_assistant(self) -> None:
        if self._messages and self._messages[-1]["role"] == "assistant":
            self._messages.pop()
```

- [ ] **Step 6: Rewire `main()` to use the provider + loop**

In `scripts/agent.py` `main()`, replace the block from `client = Anthropic()` (and the entire `for turn in range(...)` loop plus the `meta = {...}` assembly) with provider construction + `run_agent_loop`. Concretely:

Delete lines that create `client = Anthropic()` and the whole `for turn` loop and the inline `total_*`/`transcript` bookkeeping. Replace with:

```python
    from scripts.providers import AnthropicProvider  # local import keeps GeminiProvider optional

    system_text = SYSTEM_PROMPT.format(max_turns=args.max_turns)
    if args.calibrate:
        system_text += CALIBRATION_INSTRUCTION

    provider = AnthropicProvider(args.model, system_text)
    provider.add_user_text(instruction)

    loop_meta = run_agent_loop(provider, sandbox, args.max_turns, console)

    meta = {
        "task": args.task,
        "variant": variant_label,
        "base_variant": args.variant,
        "calibrate": args.calibrate,
        "model": args.model,
        "max_turns": args.max_turns,
        "turns_used": loop_meta["turns_used"],
        "stop_reason": loop_meta["stop_reason"],
        "tokens": loop_meta["tokens"],
        "produced_trace": loop_meta["produced_trace"],
        "produced_answer": loop_meta["produced_answer"],
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    (sandbox / "meta.json").write_text(json.dumps(meta, indent=2))
    (sandbox / "transcript.json").write_text(json.dumps(loop_meta["_transcript"], indent=2))

    console.print(f"\n[bold]Summary[/]  turns={meta['turns_used']}/{args.max_turns} "
                  f"in={meta['tokens']['input_total']:,} out={meta['tokens']['output_total']:,} "
                  f"trace={meta['produced_trace']} answer={meta['produced_answer']}")
    console.print(f"[green]done[/] -> {sandbox}/")
```

Also remove the now-unused module-level `from anthropic import Anthropic` import at the top (the provider imports it lazily), and keep `RUN_PYTHON_TOOL` deleted/migrated — replace its module use; if `RUN_PYTHON_TOOL` is no longer referenced in agent.py, delete its definition (lines 90-106).

- [ ] **Step 7: Full test suite passes**

Run: `uv run pytest -q`
Expected: PASS (all tests).

- [ ] **Step 8: CRITICAL — Anthropic parity smoke test (real API, 1 run)**

Run a single cheap real run with the refactored code and confirm artifacts + meta schema are intact and the judge still parses:

```bash
uv run --env-file .env scripts/agent.py --task da-3-4 --variant stripped --model claude-opus-4-7 --max-turns 20
# find the new run dir:
NEW=$(ls -dt runs/agent/da-3-4/claude_opus_4_7/stripped/*/ | head -1)
uv run --env-file .env scripts/judge.py --run-dir "$NEW"
uv run python -c "import json; m=json.load(open('$NEW/meta.json')); assert set(['task','variant','model','turns_used','tokens','produced_trace','produced_answer','stop_reason']) <= set(m); assert set(['input_total','output_total']) <= set(m['tokens']); print('meta schema OK', m['turns_used'], 'turns')"
```
Expected: agent produces `trace.md`+`answer.txt`, judge prints a score, meta-schema assertion prints `meta schema OK`.

- [ ] **Step 9: Commit**

```bash
git add scripts/agent.py scripts/providers.py tests/test_agent_loop.py
git commit -m "refactor: provider-agnostic agent loop + AnthropicProvider (parity verified)"
```

---

### Task 4: Implement GeminiProvider

Translate the neutral contract to `google-genai`'s manual function-calling API. Unit-test request construction + response normalization against constructed fake SDK objects (no network).

**Files:**
- Modify: `scripts/providers.py` (add `GeminiProvider` + stop-reason normalizer)
- Create: `tests/test_gemini_provider.py`

- [ ] **Step 1: Write the failing normalization test**

Create `tests/test_gemini_provider.py`:

```python
from types import SimpleNamespace

from scripts.providers import _normalize_gemini_stop, GeminiProvider


def test_normalize_stop_reasons():
    assert _normalize_gemini_stop("STOP", has_calls=True) == "tool_use"
    assert _normalize_gemini_stop("STOP", has_calls=False) == "end_turn"
    assert _normalize_gemini_stop("MAX_TOKENS", has_calls=False) == "max_tokens"
    assert _normalize_gemini_stop("MAX_TOKENS", has_calls=True) == "max_tokens"
    assert _normalize_gemini_stop("SAFETY", has_calls=False) == "SAFETY"


def test_parse_response_extracts_calls_and_usage():
    # Build a fake google-genai response shape.
    fc = SimpleNamespace(id="call_1", name="run_python", args={"code": "print(1)"})
    part_text = SimpleNamespace(text="reasoning", function_call=None)
    part_call = SimpleNamespace(text=None, function_call=fc)
    candidate = SimpleNamespace(
        content=SimpleNamespace(parts=[part_text, part_call]),
        finish_reason="STOP",
    )
    resp = SimpleNamespace(
        candidates=[candidate],
        usage_metadata=SimpleNamespace(prompt_token_count=123, candidates_token_count=45,
                                       cached_content_token_count=0),
    )
    tr = GeminiProvider._parse_response(resp)
    assert tr.stop_reason == "tool_use"
    assert tr.text_blocks == ["reasoning"]
    assert tr.tool_calls[0].code == "print(1)"
    assert tr.tool_calls[0].id == "call_1"
    assert tr.in_tokens == 123
    assert tr.out_tokens == 45
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_gemini_provider.py -q`
Expected: FAIL with `ImportError: cannot import name '_normalize_gemini_stop'`.

- [ ] **Step 3: Implement GeminiProvider**

Append to `scripts/providers.py`:

```python
import itertools


def _normalize_gemini_stop(finish_reason: str, has_calls: bool) -> str:
    fr = (finish_reason or "").upper()
    if fr == "MAX_TOKENS":
        return "max_tokens"
    if has_calls:
        return "tool_use"
    if fr == "STOP":
        return "end_turn"
    return finish_reason  # SAFETY, RECITATION, etc. — pass through


class GeminiProvider(Provider):
    """Google Gen AI manual function-calling loop.

    Conversation history is a list of `types.Content` turns. We disable
    automatic function calling so we own the tool execution, exactly like the
    Anthropic loop. Gemini's implicit context caching applies automatically;
    we report cache_* as 0 since the SDK does not bill-split them the way
    Anthropic does.
    """

    def __init__(self, model: str, system_text: str, max_tokens: int = 8192):
        import os
        from google import genai
        from google.genai import types
        self._types = types
        self._client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
        self._model = model
        self._system_text = system_text
        self._max_tokens = max_tokens
        self._counter = itertools.count(1)
        fn = types.FunctionDeclaration(
            name=RUN_PYTHON_SPEC["name"],
            description=RUN_PYTHON_SPEC["description"],
            parameters_json_schema=RUN_PYTHON_SPEC["parameters"],
        )
        self._tool = types.Tool(function_declarations=[fn])
        self._config = types.GenerateContentConfig(
            system_instruction=system_text,
            max_output_tokens=max_tokens,
            tools=[self._tool],
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            tool_config=types.ToolConfig(
                function_calling_config=types.FunctionCallingConfig(mode="AUTO")),
        )
        self._contents: list = []
        self._pending_call_names: dict[str, str] = {}  # id -> function name

    def add_user_text(self, text: str) -> None:
        self._contents.append(
            self._types.Content(role="user", parts=[self._types.Part(text=text)]))

    def add_tool_results(self, results):
        parts = []
        for (tid, content, _err) in results:
            name = self._pending_call_names.get(tid, "run_python")
            parts.append(self._types.Part.from_function_response(
                name=name, response={"result": content}))
        self._contents.append(self._types.Content(role="user", parts=parts))

    def advance(self) -> TurnResult:
        backoff = 8.0
        attempts = 0
        while True:
            try:
                resp = self._client.models.generate_content(
                    model=self._model, contents=self._contents, config=self._config)
                break
            except Exception as e:  # google-genai raises ClientError/ServerError
                attempts += 1
                code = getattr(e, "code", None) or getattr(e, "status_code", None)
                if attempts > 6 or (code not in (429, 503, 500, None)):
                    raise
                time.sleep(backoff)
                backoff = min(backoff * 1.8, 60.0)
        # Append the model's turn to history verbatim for the next call.
        self._contents.append(resp.candidates[0].content)
        tr = self._parse_response(resp)
        for tc in tr.tool_calls:
            self._pending_call_names[tc.id] = "run_python"
        return tr

    def drop_last_assistant(self) -> None:
        if self._contents and getattr(self._contents[-1], "role", None) == "model":
            self._contents.pop()

    @staticmethod
    def _parse_response(resp) -> TurnResult:
        cand = resp.candidates[0]
        texts, calls = [], []
        idgen = itertools.count(1)
        for part in cand.content.parts:
            if getattr(part, "function_call", None):
                fc = part.function_call
                cid = getattr(fc, "id", None) or f"gemini_call_{next(idgen)}"
                code = (fc.args or {}).get("code", "")
                calls.append(ToolCall(id=cid, code=code))
            elif getattr(part, "text", None):
                texts.append(part.text)
        um = resp.usage_metadata
        return TurnResult(
            text_blocks=texts, tool_calls=calls,
            stop_reason=_normalize_gemini_stop(str(getattr(cand, "finish_reason", "")),
                                               has_calls=bool(calls)),
            in_tokens=getattr(um, "prompt_token_count", 0) or 0,
            out_tokens=getattr(um, "candidates_token_count", 0) or 0,
            cache_create=0,
            cache_read=getattr(um, "cached_content_token_count", 0) or 0,
        )
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_gemini_provider.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Full suite green**

Run: `uv run pytest -q`
Expected: PASS (all).

- [ ] **Step 6: Commit**

```bash
git add scripts/providers.py tests/test_gemini_provider.py
git commit -m "feat: GeminiProvider (google-genai manual function calling)"
```

---

### Task 5: Model→provider routing + API-key gating

**Files:**
- Modify: `scripts/providers.py` (add `make_provider`)
- Modify: `scripts/agent.py` (`main()` uses `make_provider`; gate on the right key)
- Create: `tests/test_make_provider.py`

- [ ] **Step 1: Write the failing routing test**

Create `tests/test_make_provider.py`:

```python
import pytest
from scripts.providers import make_provider


def test_routes_by_prefix(monkeypatch):
    # Do not construct real clients: patch the classes to record the choice.
    import scripts.providers as P
    chosen = {}
    monkeypatch.setattr(P, "AnthropicProvider", lambda *a, **k: chosen.setdefault("p", "anthropic"))
    monkeypatch.setattr(P, "GeminiProvider", lambda *a, **k: chosen.setdefault("p", "gemini"))
    make_provider("claude-opus-4-7", "sys")
    assert chosen["p"] == "anthropic"
    chosen.clear()
    make_provider("gemini-3-pro", "sys")
    assert chosen["p"] == "gemini"


def test_unknown_model_raises():
    with pytest.raises(ValueError, match="Unknown model"):
        make_provider("llama-3", "sys")
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_make_provider.py -q`
Expected: FAIL with `ImportError: cannot import name 'make_provider'`.

- [ ] **Step 3: Implement make_provider**

Append to `scripts/providers.py`:

```python
def make_provider(model: str, system_text: str, max_tokens: int = 8192) -> Provider:
    if model.startswith("claude"):
        return AnthropicProvider(model, system_text, max_tokens)
    if model.startswith("gemini"):
        return GeminiProvider(model, system_text, max_tokens)
    raise ValueError(f"Unknown model provider for '{model}' (expected claude-* or gemini-*)")
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_make_provider.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Wire make_provider + key gating into main()**

In `scripts/agent.py`:

Replace the `load_dotenv()` key check block (currently asserts `ANTHROPIC_API_KEY`) with a model-aware gate:

```python
    load_dotenv()
    if args.model.startswith("claude") and not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("ANTHROPIC_API_KEY missing")
    if args.model.startswith("gemini"):
        key = os.environ.get("GEMINI_API_KEY", "")
        if not key or key == "REPLACE_WITH_YOUR_GEMINI_API_KEY":
            sys.exit("GEMINI_API_KEY missing or still the placeholder — add your real key to .env")
```

And replace `from scripts.providers import AnthropicProvider` + `provider = AnthropicProvider(...)` (from Task 3 Step 6) with:

```python
    from scripts.providers import make_provider
    provider = make_provider(args.model, system_text)
```

- [ ] **Step 6: Full suite + help smoke**

Run: `uv run pytest -q && uv run --env-file .env scripts/agent.py --help`
Expected: tests PASS; `--help` prints usage including `--model`.

- [ ] **Step 7: Commit**

```bash
git add scripts/agent.py scripts/providers.py tests/test_make_provider.py
git commit -m "feat: model->provider routing + per-provider API key gating"
```

---

### Task 6: Gemini live smoke test + E2 batch re-runs + re-judge

**Blocked on:** a real `GEMINI_API_KEY` in `.env` and the exact Gemini 3 model ID. This task executes the experiment; no new app code except a thin batch driver.

**Files:**
- Create: `scripts/run_gemini_batch.sh`

- [ ] **Step 1: Confirm the model ID + a 1-call connectivity check**

Run (model ID confirmed by user: `gemini-3.1-pro-preview`):

```bash
MODEL=gemini-3.1-pro-preview
uv run --env-file .env python -c "
import os; from google import genai
c=genai.Client(api_key=os.environ['GEMINI_API_KEY'])
r=c.models.generate_content(model='$MODEL', contents='reply with the single word OK')
print(r.text)"
```
Expected: prints `OK` (or similar). If the model ID is wrong, list models:
`uv run --env-file .env python -c "import os;from google import genai;[print(m.name) for m in genai.Client(api_key=os.environ['GEMINI_API_KEY']).models.list()]"`

- [ ] **Step 2: One real Gemini agent run (parity of artifacts)**

```bash
uv run --env-file .env scripts/agent.py --task da-3-4 --variant stripped --model $MODEL --max-turns 20
NEW=$(ls -dt runs/agent/da-3-4/gemini*/stripped/*/ | head -1)
uv run python -c "import json;m=json.load(open('$NEW/meta.json'));print('OK', m['model'], m['turns_used'], 'turns', 'trace=',m['produced_trace'])"
uv run --env-file .env scripts/judge.py --run-dir "$NEW"
```
Expected: meta prints with `gemini*` model slug; trace/answer produced; judge scores it. If trajectory `_tool_calls/*.py` are present, trust_metrics will work unchanged.

- [ ] **Step 3: Write the batch driver**

Create `scripts/run_gemini_batch.sh`:

```bash
#!/usr/bin/env bash
# Re-run the 6-task refusal + calibration battery on Gemini for cross-vendor
# comparison. Mirrors the Opus runs the design spec describes.
set -euo pipefail
MODEL="${1:?usage: run_gemini_batch.sh <gemini-model-id>}"
K_ADV="${2:-3}"      # runs per adversarial variant
K_CAL="${3:-5}"      # calibrate runs per task
cd "$(dirname "$0")/.."

ADV_VARIANTS=(
  da-12-4_drop_survival da-12-4_tiny_n
  da-3-4_drop_response da-3-4_single_group
  da-5-1_drop_pdac da-5-1_drop_tier
  da-13-3_drop_pvalues da-13-3_drop_pct_fat
  da-17-1_drop_disease
  da-20-1_drop_cell_line da-20-1_single_cell_type
)
CAL_TASKS=(da-3-4 da-5-1 da-12-4 da-13-3 da-17-1 da-20-1)

# NOTE: adversarial variants are separate task dirs under data/biomnibench-da/;
# they are launched with --task <variant> --variant contaminated, matching how
# the Opus adversarial runs were produced.
for v in "${ADV_VARIANTS[@]}"; do
  for i in $(seq 1 "$K_ADV"); do
    uv run --env-file .env scripts/agent.py --task "$v" --variant contaminated --model "$MODEL" --max-turns 25 || true
  done
done
for t in "${CAL_TASKS[@]}"; do
  for i in $(seq 1 "$K_CAL"); do
    uv run --env-file .env scripts/agent.py --task "$t" --variant contaminated --calibrate --model "$MODEL" --max-turns 25 || true
  done
done
echo "batch done for $MODEL"
```

Make executable: `chmod +x scripts/run_gemini_batch.sh`

- [ ] **Step 4: Verify the adversarial task dirs exist for the driver**

Run: `for v in da-12-4_drop_survival da-3-4_drop_response da-20-1_single_cell_type; do test -d data/biomnibench-da/$v && echo "ok $v" || echo "MISSING $v"; done`
Expected: all `ok`. (If any MISSING, the variant dataset needs creating first — out of scope here; note and stop.)

- [ ] **Step 5: Launch the batch (cost-gated — confirm before running full)**

Run a SINGLE variant first to estimate cost:
```bash
uv run --env-file .env scripts/agent.py --task da-3-4_drop_response --variant contaminated --model $MODEL --max-turns 25
```
Inspect token totals in the printed summary, estimate full-batch cost, then launch:
```bash
./scripts/run_gemini_batch.sh $MODEL 3 5
```
Expected: ~33 adversarial + ~30 calibrate Gemini runs under `runs/agent/*/gemini*/`.

- [ ] **Step 6: Re-judge the Gemini runs**

```bash
# rubric + calibration judging for each calibrate task
for t in da-3-4 da-5-1 da-12-4 da-13-3 da-17-1 da-20-1; do
  for d in runs/agent/$t/gemini*/contaminated_calibrate/*/; do
    uv run --env-file .env scripts/judge.py --run-dir "$d"
  done
done
# refusal judging for each adversarial variant
for v in da-12-4_drop_survival da-12-4_tiny_n da-3-4_drop_response da-3-4_single_group da-5-1_drop_pdac da-5-1_drop_tier da-13-3_drop_pvalues da-13-3_drop_pct_fat da-17-1_drop_disease da-20-1_drop_cell_line da-20-1_single_cell_type; do
  uv run --env-file .env scripts/refusal_judge.py --task "$v" --all
done
```
Expected: `judge.json` + `refusal_judgment.json` sidecars written under the Gemini run dirs.

- [ ] **Step 7: Commit (code + driver only; runs are data)**

```bash
git add scripts/run_gemini_batch.sh
git commit -m "feat: Gemini cross-vendor batch driver for refusal + calibration re-runs"
```

---

### Task 7: Extend aggregation to a 2-model grid + update RESULTS.md

**Files:**
- Modify: `scripts/calibration_ece.py` (group by model)
- Create: `scripts/refusal_totals.py` (per-model refusal distribution)
- Modify: `RESULTS.md`

- [ ] **Step 1: Write the failing per-model ECE test**

Create `tests/test_calibration_by_model.py`:

```python
from scripts.calibration_ece import ece_brier


def test_ece_handles_grouped_records():
    recs = [
        {"task": "t", "variant": "v", "conf": "HIGH", "success": 0},
        {"task": "t", "variant": "v", "conf": "HIGH", "success": 1},
    ]
    out = ece_brier(recs)
    assert out["n"] == 2
    assert 0.0 <= out["ECE"] <= 1.0
```

- [ ] **Step 2: Run to verify it passes (regression guard for existing fn)**

Run: `uv run pytest tests/test_calibration_by_model.py -q`
Expected: PASS — confirms `ece_brier` is importable and stable before we add model grouping.

- [ ] **Step 3: Add a `--by-model` axis to calibration_ece.py**

In `scripts/calibration_ece.py`, `load_calibrate_runs()` already captures the run dir; add the model slug to each record. Change the record append to include model:

```python
        out.append({"task": d.parts[-4], "model": d.parts[-3], "variant": d.parts[-2],
                    "conf": conf, "success": succ})
```

In `main()`, when a new `--by-model` flag is passed, group by `(model, task)` instead of `task`:

```python
    ap.add_argument("--by-model", action="store_true", help="group ECE by (model, task)")
```

and:

```python
    if args.by_model:
        from collections import defaultdict
        grid = defaultdict(list)
        for r in records:
            grid[(r["model"], r["task"])].append(r)
        print(f"{'model':<16}{'task':<9}{'n':<4}{'succ':<7}{'ECE':<7}")
        for (m, t), rs in sorted(grid.items()):
            x = ece_brier(rs)
            print(f"{m:<16}{t:<9}{x['n']:<4}{x['success_rate']:<7.2f}{x['ECE']:<7.2f}")
        return
```

- [ ] **Step 4: Run the new axis**

Run: `uv run scripts/calibration_ece.py --by-model`
Expected: a table with both `claude_opus_4_7` and `gemini_*` rows (Gemini rows appear once Task 6 has produced+judged runs).

- [ ] **Step 5: Create refusal_totals.py (per-model)**

Create `scripts/refusal_totals.py`:

```python
"""Per-model refusal distribution across all adversarial variants."""
from __future__ import annotations
import glob, json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def main() -> None:
    grid = defaultdict(lambda: defaultdict(int))
    for f in glob.glob(str(ROOT / "runs/agent/*/*/*/*/refusal_judgment.json")):
        d = Path(f)
        model = d.parts[-4]
        cls = json.loads(d.read_text()).get("classification", "?")
        grid[model][cls] += 1
    for model, dist in sorted(grid.items()):
        total = sum(dist.values())
        appr = dist.get("APPROPRIATE_REFUSAL", 0)
        print(f"\n{model}: {total} runs, APPROPRIATE_REFUSAL {appr}/{total} = {100*appr/total:.1f}%")
        for k, v in sorted(dist.items(), key=lambda kv: -kv[1]):
            print(f"  {k}: {v}")

if __name__ == "__main__":
    main()
```

- [ ] **Step 6: Run per-model refusal totals**

Run: `uv run scripts/refusal_totals.py`
Expected: a per-model block; `claude_opus_4_7` shows the known 0/33; `gemini_*` shows its distribution.

- [ ] **Step 7: Update RESULTS.md with the 2-model grid**

Add a subsection "Cross-vendor replication (added <date>)" under the N=6 section, with two tables filled from Steps 4 & 6 output:
- per-model refusal rate (Opus vs Gemini)
- per-model ECE-vs-success table

If Gemini's refusal rate is also ≈0: state the cross-vendor generalization. If materially higher: report it as a cross-vendor difference and (per the spec's risk note) reframe the abstract claim to "model-dependent; at least one frontier agent under-refuses with a fabrication pathway." Use the actual measured numbers — do not pre-write the conclusion.

- [ ] **Step 8: Commit**

```bash
git add scripts/calibration_ece.py scripts/refusal_totals.py tests/test_calibration_by_model.py RESULTS.md
git commit -m "feat: per-model ECE + refusal aggregation; RESULTS.md cross-vendor grid"
```

---

## Self-Review notes

- **Spec coverage:** E1 → Tasks 2–5; E2 → Task 6; E4 → Task 7 (calibration_ece `--by-model`, refusal_totals); E5 → Task 7 Step 7. LAB-Bench2 (E3) intentionally deferred to a separate plan (noted in header).
- **Invariant coverage:** meta schema asserted in Task 3 Step 8 + Task 6 Step 2; `_tool_calls/*.py` produced by the shared loop (Task 3) and asserted in `test_agent_loop`; model_slug naming unchanged (uses existing `setup_sandbox`).
- **Not assuming the result:** Task 7 Step 7 explicitly forbids pre-writing the cross-vendor conclusion.
- **Open externalities flagged:** real `GEMINI_API_KEY` (Task 6 blocked), exact Gemini model ID (Task 6 Step 1), adversarial variant datasets must pre-exist (Task 6 Step 4).
