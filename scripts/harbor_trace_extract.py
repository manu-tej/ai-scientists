"""Extract a judge-ready (trace, answer) pair from a Harbor agent tool-call log.

Harbor's coding-agent harnesses (codex, claude-code, gemini-cli) emit stream-json
to agent/<harness>.txt. With --disable-verification the in-container /app/answer.txt
isn't copied to the host, so we recover the agent's decision signal from the log:

  - codex      : lines are repr-wrapped strings containing {"type":"agent_message",
                 "text":...} events and command/file-write events.
  - claude-code: stream-json with assistant text blocks, Write/Bash tool_use
                 (the agent writes /app/answer.txt via `cat > … <<EOF` or Write),
                 and a final {"type":"result","result":...} event.

We return:
  trace  = concatenation of the agent's natural-language messages (its reasoning)
  answer = the best recoverable final answer (last substantial agent message; for
           claude-code also the final "result" text), plus any answer.txt content
           we can recover from a Write/heredoc in the log.

This is intentionally lossy but captures what a refusal judge needs: did the agent
flag impossibility, and what did it ultimately assert.
"""
from __future__ import annotations

import json
import re
from pathlib import Path


def _unescape(s: str) -> str:
    try:
        return json.loads('"' + s + '"')
    except Exception:
        return s


def extract_codex(text: str) -> tuple[str, str]:
    # codex emits single-line JSON events:
    #   {"type":"item.completed","item":{...,"type":"agent_message","text":"…"}}
    # The agent's natural-language turns are agent_message.text (single-escaped).
    msgs = [_unescape(m) for m in
            re.findall(r'"type":"agent_message","text":"((?:[^"\\]|\\.)*)"', text)]
    reason = [_unescape(m) for m in
              re.findall(r'"type":"agent_reasoning","text":"((?:[^"\\]|\\.)*)"', text)]
    trace = "\n\n".join(reason + msgs)
    answer = msgs[-1] if msgs else ""
    return trace, answer


def extract_claude_code(text: str) -> tuple[str, str]:
    # assistant natural-language text blocks
    texts = [_unescape(m) for m in
             re.findall(r'"type":"text","text":"((?:[^"\\]|\\.)*)"', text)]
    # final result event
    res = re.findall(r'"type":"result"[^\n]*?"result":"((?:[^"\\]|\\.)*)"', text)
    final = _unescape(res[-1]) if res else (texts[-1] if texts else "")
    trace = "\n\n".join(texts)
    return trace, final


def recover_answer_file(text: str) -> str:
    """Best-effort: pull /app/answer.txt content if the agent wrote it via a
    Write tool_use (content inline) — codex usually generates it from a script
    (unrecoverable), claude-code sometimes writes it directly."""
    # Write tool_use with file_path answer.txt
    for m in re.finditer(r'"file_path":"([^"]*answer\.txt)"[^}]*?"content":"((?:[^"\\]|\\.)*)"', text):
        return _unescape(m.group(2))
    return ""


def extract(trace_path: Path) -> dict:
    text = trace_path.read_text(encoding="utf-8", errors="ignore")
    harness = trace_path.stem  # codex | claude-code | gemini-cli
    if harness == "codex":
        trace, answer = extract_codex(text)
    elif harness in ("claude-code", "gemini-cli", "gemini"):
        trace, answer = extract_claude_code(text)
    else:
        trace, answer = "", ""
    recovered = recover_answer_file(text)
    if recovered:
        answer = recovered + "\n\n[final-message]\n" + answer
    return {
        "harness": harness,
        "trace_chars": len(trace),
        "answer_chars": len(answer),
        "trace": trace,
        "answer": answer,
    }


if __name__ == "__main__":
    import sys
    d = extract(Path(sys.argv[1]))
    out = {k: v for k, v in d.items() if k not in ("trace", "answer")}
    out["answer_preview"] = d["answer"][:500]
    out["trace_tail"] = d["trace"][-500:]
    print(json.dumps(out, indent=2))
