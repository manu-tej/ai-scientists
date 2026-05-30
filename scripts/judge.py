"""Minimal LLM judge that scores an agent's (trace.md, answer.txt) against
the task's rubric. Mirrors the structure of BiomniBench's tests/llm_judge.py
but runs locally and uses Claude as the judge by default.

Usage:
    uv run --env-file .env scripts/judge.py \\
        --run-dir runs/agent/da-12-4/claude_haiku_4_5/contaminated/<ts>
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
from rich.console import Console

ROOT = Path(__file__).resolve().parents[1]
DATASET_ROOT = ROOT / "data/biomnibench-da"
DEFAULT_JUDGE_MODEL = "claude-opus-4-7"

JUDGE_PROMPT = """You are an expert evaluator for a data analysis task.

Evaluate the agent's work using the following rubric:
{rubric}

Here is the agent's analysis trace:
<trace>
{trace}
</trace>

Here is the agent's final answer:
<answer>
{answer}
</answer>

For each criterion in the rubric, choose ONE level: A, B, or C - based purely on
which level description best describes the agent's work. Do not output numerical
points; the score for each level is computed automatically from the rubric.

You MUST respond with a JSON object in exactly this format:
{{
  "criteria": {{
    "criterion_1": {{"level": "A", "reason": "<one-sentence explanation>"}},
    "criterion_2": {{"level": "B", "reason": "<one-sentence explanation>"}}
  }},
  "overall_reasoning": "<short summary>"
}}

Each "level" value must be exactly the single character "A", "B", or "C".
Only output the JSON object, nothing else.
"""


def parse_rubric_levels(rubric_text: str) -> dict:
    """Reuse BiomniBench's rubric parsing: per-criterion A/B/C point table."""
    out: dict = {}
    parts = re.split(r"^Criterion\s+(\d+)\s*:", rubric_text, flags=re.MULTILINE)
    for i in range(1, len(parts), 2):
        n = parts[i].strip()
        body = parts[i + 1] if i + 1 < len(parts) else ""
        levels: dict = {}
        m = re.search(r"Levels:\s*((?:[A-Z]=-?\d+\s*)+)", body)
        if m:
            for lm in re.finditer(r"([A-Z])=(-?\d+)", m.group(1)):
                levels[lm.group(1).upper()] = int(lm.group(2))
        if levels:
            out[f"criterion_{n}"] = levels
    return out


def judge(client: Anthropic, model: str, rubric: str, trace: str, answer: str) -> dict:
    prompt = JUDGE_PROMPT.format(rubric=rubric, trace=trace, answer=answer)
    msg = client.messages.create(
        model=model, max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )
    text = "".join(b.text for b in msg.content if hasattr(b, "text")).strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as e:
        parsed = {"_parse_error": str(e), "raw": text}
    parsed["_tokens"] = {"in": msg.usage.input_tokens, "out": msg.usage.output_tokens}
    return parsed


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--run-dir", type=Path, required=True,
                   help="Path to an agent run directory (must contain trace.md, answer.txt, meta.json)")
    p.add_argument("--judge-model", default=DEFAULT_JUDGE_MODEL)
    args = p.parse_args()

    load_dotenv()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("ANTHROPIC_API_KEY missing")
    console = Console()
    client = Anthropic()

    run_dir = args.run_dir.resolve()
    meta = json.loads((run_dir / "meta.json").read_text())
    task_id = meta["task"]
    rubric = (DATASET_ROOT / task_id / "tests" / "rubric.txt").read_text()
    trace_path = run_dir / "trace.md"
    answer_path = run_dir / "answer.txt"
    if not trace_path.exists() or not answer_path.exists():
        sys.exit(f"Missing trace.md or answer.txt in {run_dir}")
    trace = trace_path.read_text()
    answer = answer_path.read_text()

    console.print(f"[cyan]judging:[/] {run_dir}")
    console.print(f"  task: {task_id}  variant: {meta['variant']}  agent: {meta['model']}")
    console.print(f"  judge model: {args.judge_model}")

    levels = parse_rubric_levels(rubric)
    result = judge(client, args.judge_model, rubric, trace, answer)
    if "_parse_error" in result:
        console.print(f"[red]judge JSON parse error: {result['_parse_error']}[/]")
        (run_dir / "judge.json").write_text(json.dumps(result, indent=2))
        sys.exit(1)

    # Compute score from level table
    total = 0
    breakdown = []
    for cname, c_levels in levels.items():
        chosen = result.get("criteria", {}).get(cname, {}).get("level")
        pts = c_levels.get(chosen, 0)
        total += pts
        breakdown.append({
            "criterion": cname,
            "level": chosen,
            "points": pts,
            "max_points": max(c_levels.values()),
            "reason": result.get("criteria", {}).get(cname, {}).get("reason", ""),
        })

    output = {
        "task": task_id,
        "variant": meta["variant"],
        "agent_model": meta["model"],
        "judge_model": args.judge_model,
        "score": total,
        "max_score": sum(max(c.values()) for c in levels.values() if max(c.values()) > 0),
        "breakdown": breakdown,
        "overall_reasoning": result.get("overall_reasoning", ""),
        "judge_tokens": result["_tokens"],
    }
    (run_dir / "judge.json").write_text(json.dumps(output, indent=2))

    console.print(f"\n[bold]Score: {total} / {output['max_score']}[/]")
    for b in breakdown:
        ind = "✓" if b["points"] == b["max_points"] else ("∼" if b["points"] > 0 else "✗")
        console.print(f"  {ind} {b['criterion']:<14} [{b['level']}] {b['points']:>3}/{b['max_points']:<3}  {b['reason']}")
    console.print(f"\n[dim]{output['overall_reasoning']}[/]")
    console.print(f"\n[green]done[/] -> {run_dir}/judge.json")


if __name__ == "__main__":
    main()
