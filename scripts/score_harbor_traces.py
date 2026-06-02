"""Score Harbor agent traces for abstention/refusal on unanswerable variants.

Reuses the judge + REFUSAL_DESCRIPTIONS from refusal_judge.py, but reads the
agent's behavior from Harbor tool-call logs (agent/<harness>.txt) via
harbor_trace_extract, since --disable-verification leaves no host-side answer.txt.

Discovers cells under one or more roots, each laid out as
   <root>/.../<task>__<id>/agent/<harness>.txt
Writes a refusal_judgment.json next to each trace, and a combined
runs/refusal_table.json summary.

Usage:
  uv run --env-file .env scripts/score_harbor_traces.py \
      --root runs/harbor_matrix --root runs/traces_codex
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

from anthropic import Anthropic
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.refusal_judge import REFUSAL_DESCRIPTIONS, JUDGE_PROMPT_TEMPLATE, DEFAULT_JUDGE_MODEL  # noqa: E402
from scripts.harbor_trace_extract import extract  # noqa: E402

TASK_RE = re.compile(r"(da-\d+-\d+_[a-z0-9_]+?)__[A-Za-z0-9]+")


def task_of(trace_path: Path) -> str | None:
    for part in trace_path.parts:
        m = TASK_RE.match(part)
        if m:
            return m.group(1)
    return None


def judge(client: Anthropic, model: str, context: str, trace: str, answer: str) -> dict:
    # bound trace size to keep judge cost sane; keep head+tail (problem detection
    # usually appears early; the conclusion late)
    if len(trace) > 12000:
        trace = trace[:6000] + "\n…[trace truncated]…\n" + trace[-6000:]
    prompt = JUDGE_PROMPT_TEMPLATE.format(context=context, trace=trace, answer=answer or "(no answer recovered)")
    msg = client.messages.create(model=model, max_tokens=1024,
                                 messages=[{"role": "user", "content": prompt}])
    text = "".join(b.text for b in msg.content if hasattr(b, "text")).strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1].removeprefix("json").strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as e:
        parsed = {"_parse_error": str(e), "raw": text[:300]}
    parsed["_tokens"] = {"in": msg.usage.input_tokens, "out": msg.usage.output_tokens}
    return parsed


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", action="append", required=True, type=Path)
    ap.add_argument("--judge-model", default=DEFAULT_JUDGE_MODEL)
    ap.add_argument("--limit", type=int, default=0, help="score only first N (smoke)")
    args = ap.parse_args()

    load_dotenv()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("ANTHROPIC_API_KEY missing")
    client = Anthropic()

    # discover traces
    cells = []
    for root in args.root:
        for tp in sorted(root.rglob("agent/*.txt")):
            if tp.stem not in ("codex", "claude-code", "gemini-cli", "gemini"):
                continue
            task = task_of(tp)
            if not task or task not in REFUSAL_DESCRIPTIONS:
                continue
            cells.append((task, tp.stem, tp))

    if args.limit:
        cells = cells[:args.limit]

    print(f"discovered {len(cells)} scorable cells")
    table = []
    for task, harness, tp in cells:
        ex = extract(tp)
        if ex["trace_chars"] == 0 and ex["answer_chars"] == 0:
            verdict = {"classification": "INCOMPLETE", "reason": "empty trace"}
        else:
            verdict = judge(client, args.judge_model,
                            REFUSAL_DESCRIPTIONS[task], ex["trace"], ex["answer"])
        sidecar = tp.parent.parent / "refusal_judgment.json"
        sidecar.write_text(json.dumps(
            {"task": task, "harness": harness, **verdict,
             "trace_chars": ex["trace_chars"], "answer_chars": ex["answer_chars"]},
            indent=2))
        row = {"task": task, "harness": harness,
               "classification": verdict.get("classification", "?"),
               "detected_problem": verdict.get("detected_problem"),
               "fabricated_data": verdict.get("fabricated_data"),
               "reason": verdict.get("reason", "")[:140]}
        table.append(row)
        print(f"  {harness:12} {task:26} {row['classification']:22} "
              f"detected={row['detected_problem']} fab={row['fabricated_data']}")

    out = ROOT / "runs/refusal_table.json"
    out.write_text(json.dumps(table, indent=2))
    print(f"\nwrote {out} ({len(table)} rows)")


if __name__ == "__main__":
    main()
