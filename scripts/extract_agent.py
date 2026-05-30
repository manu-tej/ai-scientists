"""LLM-judge extractor for agent run traces (vs. prediction probes).

Where scripts/extract.py extracts structured fields from prediction-only
responses, this script extracts the *computed analytical values* an agent
reported in its trace.md + answer.txt. Used to populate methodological
consistency metrics across K reruns.

For da-12-4 specifically: pulls the merged cohort size, the Kocuria HR/p,
and the cohort-construction approach. Generalizable to other tasks by
adjusting the schema per task.

Usage:
    uv run --env-file .env scripts/extract_agent.py --task da-12-4 --all
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from anthropic import Anthropic
from dotenv import load_dotenv
from rich.console import Console

ROOT = Path(__file__).resolve().parents[1]
EXTRACTOR_MODEL = "claude-haiku-4-5"


# Per-task extraction schemas. Each prompt asks for the analytical values
# that actually drive scoring on that task.
TASK_SCHEMAS: dict[str, str] = {
    "da-12-4": """Extract the agent's computed analytical values from this trace.

You MUST output exactly this JSON (no markdown fences, no commentary):
{
  "merged_cohort_n_samples": <int — number of samples in the final matched cohort the agent used for Cox PH analysis; null if not stated>,
  "n_events": <int — number of survival events / deaths in the final cohort; null if not stated>,
  "kocuria_hazard_ratio": <float — Kocuria's hazard ratio; null if not stated>,
  "kocuria_p_value": <float — Kocuria's p-value from univariate Cox PH; null if not stated>,
  "kocuria_call": <"yes" | "no" | "borderline" — agent's final conclusion about Kocuria being significantly associated with poor prognosis>,
  "cohort_construction_logic": <string — short (≤120 chars) description of how the agent constructed the matched cohort>,
  "deduplication_done": <true if the agent explicitly deduplicated samples-per-patient; false otherwise>,
  "tumor_only_filter": <true if the agent restricted to tumor (not normal/recurrent) samples; false otherwise>,
  "confidence_expressed": <"high" | "moderate" | "low" | "none" — agent's expressed confidence in its conclusion>
}
""",
}


EXTRACTION_PROMPT_TEMPLATE = """{schema}

TRACE:
<<<
{trace}
>>>

ANSWER:
<<<
{answer}
>>>
"""


def extract(client: Anthropic, schema: str, trace: str, answer: str) -> dict:
    prompt = EXTRACTION_PROMPT_TEMPLATE.format(schema=schema, trace=trace, answer=answer)
    msg = client.messages.create(
        model=EXTRACTOR_MODEL,
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )
    text = "".join(b.text for b in msg.content if hasattr(b, "text")).strip()
    # Strip markdown fences if present
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
    p.add_argument("--task", required=True, help="Task ID (must be in TASK_SCHEMAS)")
    p.add_argument("--all", action="store_true", help="Extract every run under runs/agent/<task>/")
    p.add_argument("--skip-existing", action="store_true",
                   help="Skip runs that already have trace_extraction.json")
    p.add_argument("--run-dir", type=Path, help="Extract a single run dir")
    args = p.parse_args()

    if args.task not in TASK_SCHEMAS:
        sys.exit(f"No extraction schema defined for task '{args.task}'. Available: {list(TASK_SCHEMAS)}")
    schema = TASK_SCHEMAS[args.task]

    load_dotenv()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("ANTHROPIC_API_KEY missing")
    console = Console()
    client = Anthropic()

    # Build worklist
    if args.run_dir:
        worklist = [args.run_dir]
    elif args.all:
        task_root = ROOT / f"runs/agent/{args.task}"
        worklist = []
        for run in sorted(task_root.rglob("meta.json")):
            worklist.append(run.parent)
    else:
        sys.exit("Provide --all or --run-dir")

    console.print(f"[bold]Extracting {len(worklist)} agent run(s) for task {args.task}[/]")
    skipped = 0
    n_extracted = 0
    for run_dir in worklist:
        trace = run_dir / "trace.md"
        answer = run_dir / "answer.txt"
        sidecar = run_dir / "trace_extraction.json"
        if not trace.exists() or not answer.exists():
            continue
        if args.skip_existing and sidecar.exists():
            skipped += 1
            continue
        result = extract(client, schema, trace.read_text(), answer.read_text())
        sidecar.write_text(json.dumps(result, indent=2))
        n_extracted += 1
        # Show useful fields
        parts = run_dir.parts
        variant = parts[-2]
        ts = parts[-1]
        n = result.get("merged_cohort_n_samples")
        hr = result.get("kocuria_hazard_ratio")
        pv = result.get("kocuria_p_value")
        call = result.get("kocuria_call")
        dedup = result.get("deduplication_done")
        tumor = result.get("tumor_only_filter")
        console.print(
            f"  {variant:<14} {ts:<22}  n={n}  HR={hr}  p={pv}  call={call}  dedup={dedup}  tumor_only={tumor}"
        )

    if skipped:
        console.print(f"[dim]  skipped {skipped} (already extracted)[/]")
    console.print(f"\n[green]done[/]  extracted {n_extracted} run(s)")


if __name__ == "__main__":
    main()
