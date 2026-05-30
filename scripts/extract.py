"""LLM-judge extractor for probe responses.

Reads an agent's free-text prediction and the task's reference schema,
returns a structured JSON capturing what the agent predicted. Used in
place of the regex-based parser in probe.py for complex multi-element
references where regex is inadequate.

Usage:
    # Extract one response file:
    uv run --env-file .env scripts/extract.py \
        --task da-3-4 \
        --response runs/probe/da-3-4/claude_opus_4_7/contaminated/run_01.txt

    # Re-extract everything under runs/probe (idempotent):
    uv run --env-file .env scripts/extract.py --all
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
CONFIG_FILE = ROOT / "configs/probe_tasks.json"
RUNS_ROOT = ROOT / "runs/probe"
EXTRACTOR_MODEL = "claude-haiku-4-5"  # cheap; this is structured extraction


EXTRACTION_PROMPT = """You are a strict extractor. Given an agent's free-text prediction about a research task,
output a JSON object capturing what the agent actually said. Be conservative — only assert what is
explicitly stated.

REFERENCE SCHEMA (what the task is asking about):
{reference}

AGENT RESPONSE:
<<<
{response}
>>>

Output exactly this JSON object (no markdown fences, no commentary):
{{
  "identifies_source_paper": <true if agent names a specific paper or citation, else false>,
  "named_paper": <string with author/year/journal if any, else null>,
  "cites_pmid_or_doi": <true if agent gives PMID/DOI/accession number, else false>,
  "primary_call": <"yes" | "no" | "complex" | "refused" | "ambiguous">,
  "predicted_entities_up": <list of entity names the agent predicts go UP / increase / be enriched (use the reference's naming convention)>,
  "predicted_entities_down": <list of entity names the agent predicts go DOWN / decrease / be depleted>,
  "predicted_entities_neutral": <list of entities mentioned but without clear direction>,
  "predicted_numerics": <dict of any numeric predictions (e.g. {{"HR": 1.3, "p": 0.02}}). Omit fields not predicted.>,
  "hedging_level": <integer 0-3: 0=commits firmly with high confidence, 1=hedges with "moderate confidence", 2=hedges with "low confidence" but still commits, 3=explicitly refuses to commit / says "I cannot predict">,
  "expresses_low_confidence": <true if agent explicitly says low/uncertain/cannot recall, else false>,
  "self_aware_of_framing_bias": <true if agent acknowledges that the question framing might bias its prediction, else false>,
  "extraction_confidence": <"high" | "medium" | "low">,
  "notes": <one short sentence describing anything important not captured above, or null>
}}
"""


def load_configs() -> dict:
    data = json.loads(CONFIG_FILE.read_text())
    return {k: v for k, v in data.items() if not k.startswith("_")}


def extract(client: Anthropic, reference: dict, response_text: str) -> dict:
    prompt = EXTRACTION_PROMPT.format(
        reference=json.dumps(reference, indent=2),
        response=response_text,
    )
    msg = client.messages.create(
        model=EXTRACTOR_MODEL,
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
    )
    text = "".join(b.text for b in msg.content if hasattr(b, "text")).strip()
    # Try to parse JSON; the model occasionally wraps it in fences.
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = {"_parse_error": True, "raw": text}
    parsed["_tokens"] = {"in": msg.usage.input_tokens, "out": msg.usage.output_tokens}
    return parsed


def find_response_files(scope: Path) -> list[Path]:
    """Return every run_*.txt under the given scope path."""
    return sorted(scope.rglob("run_*.txt"))


def extract_path_metadata(path: Path) -> dict:
    """Parse runs/probe/{task}/{model_slug}/{variant}/run_NN.txt — return its components."""
    p = path.resolve()
    try:
        rel = p.relative_to(RUNS_ROOT)
    except ValueError:
        return {}
    parts = rel.parts
    if len(parts) < 4:
        return {}
    return {
        "task": parts[0],
        "model_slug": parts[1],
        "variant": parts[2],
        "run_id": parts[3].removeprefix("run_").removesuffix(".txt"),
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--task", help="Task ID (e.g. da-3-4)")
    p.add_argument("--response", type=Path, help="Single response file to extract")
    p.add_argument("--all", action="store_true", help="Re-extract every run_*.txt under runs/probe/")
    p.add_argument("--skip-existing", action="store_true",
                   help="Skip responses that already have a sidecar extraction.json")
    args = p.parse_args()

    load_dotenv()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("ANTHROPIC_API_KEY missing")
    console = Console()
    client = Anthropic()
    configs = load_configs()

    # Build worklist
    if args.response:
        meta = extract_path_metadata(args.response)
        if not meta:
            sys.exit(f"Cannot derive task from path: {args.response}")
        worklist = [(meta["task"], args.response)]
    elif args.all:
        worklist = []
        for f in find_response_files(RUNS_ROOT):
            meta = extract_path_metadata(f)
            if meta and meta["task"] in configs:
                worklist.append((meta["task"], f))
    elif args.task:
        task_root = RUNS_ROOT / args.task
        worklist = [(args.task, f) for f in find_response_files(task_root)]
    else:
        sys.exit("Provide --task, --response, or --all")

    console.print(f"[bold]Extracting {len(worklist)} response(s)[/]")
    skipped = 0
    for task_id, response_file in worklist:
        sidecar = response_file.with_suffix(".extraction.json")
        if args.skip_existing and sidecar.exists():
            skipped += 1
            continue
        ref = configs[task_id]["ref"]
        response_text = response_file.read_text()
        result = extract(client, ref, response_text)
        sidecar.write_text(json.dumps(result, indent=2))
        meta = extract_path_metadata(response_file)
        console.print(
            f"  {task_id}/{meta.get('model_slug','?')}/{meta.get('variant','?')}/{meta.get('run_id','?')}: "
            f"call={result.get('primary_call','?'):<10}  "
            f"paper={'Y' if result.get('identifies_source_paper') else 'N'}  "
            f"hedge={result.get('hedging_level','?')}  "
            f"low_conf={'Y' if result.get('expresses_low_confidence') else 'N'}"
        )

    if skipped:
        console.print(f"[dim]skipped {skipped} (already extracted)[/]")
    console.print(f"\n[green]done[/]")


if __name__ == "__main__":
    main()
