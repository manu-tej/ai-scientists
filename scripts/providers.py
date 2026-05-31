"""Provider abstraction for the agent tool-use loop.

A Provider owns the conversation history, the API call (with retry), and the
normalization of each turn into a vendor-neutral TurnResult. The agent loop in
agent.py never touches a vendor SDK directly, so every sandbox artifact it
writes (meta.json schema, _tool_calls/*.py, trace.md, answer.txt) is identical
across providers.
"""
from __future__ import annotations

import itertools
import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass


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
    @abstractmethod
    def add_user_text(self, text: str) -> None: ...
    @abstractmethod
    def add_tool_results(self, results: list[tuple[str, str, bool]]) -> None: ...
    @abstractmethod
    def advance(self) -> TurnResult: ...
    @abstractmethod
    def drop_last_assistant(self) -> None: ...


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

    def add_tool_results(self, results) -> None:
        self.tool_results_seen.append(results)

    def advance(self) -> TurnResult:
        tr = self._scripted[self._i]
        self._i += 1
        self._assistant_count += 1
        return tr

    def drop_last_assistant(self) -> None:
        self._assistant_count -= 1


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
        backoff, attempts = 8.0, 0
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


def _normalize_gemini_stop(finish_reason: str, has_calls: bool) -> str:
    # finish_reason may be a str ("STOP") or an enum repr ("FinishReason.STOP").
    fr = str(finish_reason or "").upper().split(".")[-1]
    if fr == "MAX_TOKENS":
        return "max_tokens"
    if has_calls:
        return "tool_use"
    if fr == "STOP":
        return "end_turn"
    return finish_reason


class GeminiProvider(Provider):
    """Google Gen AI manual function-calling loop (mirrors the Anthropic loop)."""

    def __init__(self, model: str, system_text: str, max_tokens: int = 8192):
        from google import genai
        from google.genai import types
        self._types = types
        self._client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
        self._model = model
        fn = types.FunctionDeclaration(
            name=RUN_PYTHON_SPEC["name"],
            description=RUN_PYTHON_SPEC["description"],
            parameters_json_schema=RUN_PYTHON_SPEC["parameters"],
        )
        self._config = types.GenerateContentConfig(
            system_instruction=system_text,
            max_output_tokens=max_tokens,
            tools=[types.Tool(function_declarations=[fn])],
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            tool_config=types.ToolConfig(
                function_calling_config=types.FunctionCallingConfig(mode="AUTO")),
        )
        self._contents: list = []
        self._idgen = itertools.count(1)

    def add_user_text(self, text: str) -> None:
        self._contents.append(
            self._types.Content(role="user", parts=[self._types.Part(text=text)]))

    def add_tool_results(self, results):
        parts = [self._types.Part.from_function_response(
            name="run_python", response={"result": content})
            for (_tid, content, _err) in results]
        self._contents.append(self._types.Content(role="user", parts=parts))

    def advance(self) -> TurnResult:
        backoff, attempts = 8.0, 0
        while True:
            try:
                resp = self._client.models.generate_content(
                    model=self._model, contents=self._contents, config=self._config)
                break
            except Exception as e:
                msg = str(e)
                # Daily-quota 429s ("per_day", multi-hour retry) are NOT transient —
                # retrying just burns the request budget. Abort immediately.
                if "per_day" in msg or "PerDay" in msg or "RequestsPerDay" in msg:
                    raise RuntimeError(f"Gemini daily quota exhausted; aborting (not retrying): {msg[:200]}") from e
                attempts += 1
                code = getattr(e, "code", None) or getattr(e, "status_code", None)
                if attempts > 6 or (code not in (429, 503, 500, None)):
                    raise
                time.sleep(backoff)
                backoff = min(backoff * 1.8, 60.0)
        self._contents.append(resp.candidates[0].content)
        return self._parse_response(resp)

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
                calls.append(ToolCall(id=cid, code=(fc.args or {}).get("code", "")))
            elif getattr(part, "text", None):
                texts.append(part.text)
        um = resp.usage_metadata
        return TurnResult(
            text_blocks=texts, tool_calls=calls,
            stop_reason=_normalize_gemini_stop(str(getattr(cand, "finish_reason", "")), bool(calls)),
            in_tokens=getattr(um, "prompt_token_count", 0) or 0,
            out_tokens=getattr(um, "candidates_token_count", 0) or 0,
            cache_create=0,
            cache_read=getattr(um, "cached_content_token_count", 0) or 0,
        )


def make_provider(model: str, system_text: str, max_tokens: int = 8192) -> Provider:
    if model.startswith("claude"):
        return AnthropicProvider(model, system_text, max_tokens)
    if model.startswith("gemini"):
        return GeminiProvider(model, system_text, max_tokens)
    raise ValueError(f"Unknown model provider for '{model}' (expected claude-* or gemini-*)")
