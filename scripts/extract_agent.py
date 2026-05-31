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

    "da-5-1": """Extract the agent's computed analytical values from this trace.

You MUST output exactly this JSON (no markdown fences, no commentary):
{
  "n_pdac_candidates": <int — number of PDAC dual-evidence candidates the agent identified; null if not stated>,
  "n_druggable_after_tier_merge": <int — number of candidates after joining with druggability tiers (S2A); null if not stated>,
  "n_top_targets": <int — number of final top targets the agent reported; null if not stated>,
  "top_targets_listed": <list of gene symbols — the final ranked top targets the agent named, in order; empty list if none stated>,
  "includes_MET": <true if MET is in the agent's top targets>,
  "includes_ERBB2": <true if ERBB2 is in the agent's top targets>,
  "includes_ATIC": <true if ATIC is in the agent's top targets>,
  "includes_GART": <true if GART is in the agent's top targets>,
  "includes_SRC": <true if SRC is in the agent's top targets>,
  "includes_MAP2K2": <true if MAP2K2 is in the agent's top targets>,
  "includes_IKBKB": <true if IKBKB is in the agent's top targets>,
  "includes_ALOX5": <true if ALOX5 is in the agent's top targets>,
  "ranking_method": <string — short description of how the agent ranked targets (e.g., "tier + CancerTypes_with_TvN+Dep")>,
  "confidence_expressed": <"high" | "moderate" | "low" | "none" — agent's expressed confidence in its conclusion>
}
""",

    "da-20-1": """Extract the agent's computed analytical values from this trace.

You MUST output exactly this JSON (no markdown fences, no commentary):
{
  "n_dmso_samples_analyzed": <int — number of DMSO baseline samples the agent included; null if not stated>,
  "baseline_dmso_only_filter": <true if the agent restricted to DMSO controls for baseline analysis; false otherwise>,
  "n_cell_types_compared": <int — number of distinct cell types the agent compared; null if not stated>,
  "clustering_method": <string — short description of method used (PCA + k-means, hierarchical, correlation, etc.)>,
  "k_clusters_used": <int — if k-means or similar, what k was used; null if not stated>,
  "most_similar_pair": <list of two cell-type names the agent determined as most similar; empty if not stated>,
  "all_distinct": <true if the agent concluded all four cell types have distinct signatures>,
  "names_AoSMC_SkMM_as_similar": <true if AoSMCs and SkMMs are paired as most similar in the agent's output (reference answer)>,
  "confidence_expressed": <"high" | "moderate" | "low" | "none" — agent's expressed confidence>
}
""",

    "da-13-3": """Extract the agent's computed analytical values from this trace.

You MUST output exactly this JSON (no markdown fences, no commentary):
{
  "n_proteins_total": <int — total proteins analyzed; null if not stated>,
  "n_significant_percent_fat": <int — proteins with adj p < 0.05 for Percent_Fat; null if not stated>,
  "n_significant_breast_volume": <int — proteins with adj p < 0.05 for Breast_Volume; null if not stated>,
  "top_proteins_percent_fat": <list of gene/protein symbols the agent ranked as top for Percent_Fat; empty if none stated>,
  "top_proteins_breast_volume": <list of gene/protein symbols the agent ranked as top for Breast_Volume; empty if none stated>,
  "includes_LEP": <true if LEP is in any top list>,
  "includes_MAPK4": <true if MAPK4 is in any top list>,
  "includes_DEFB4A": <true if DEFB4A is in any top list>,
  "includes_CA6": <true if CA6 is in any top list>,
  "includes_MUC1": <true if MUC1 is in any top list>,
  "includes_SPINT3": <true if SPINT3 is in any top list>,
  "includes_INSL3": <true if INSL3 is in any top list>,
  "ranking_method": <string — short description of how the agent ranked proteins (effect size? absolute value? signed?)>,
  "multiple_testing_correction": <string — name of correction used (e.g., "BH-FDR", "Bonferroni", "none mentioned")>,
  "confidence_expressed": <"high" | "moderate" | "low" | "none" — agent's expressed confidence in its conclusion>
}
""",

    "da-3-4": """Extract the agent's computed analytical values from this trace.

You MUST output exactly this JSON (no markdown fences, no commentary):
{
  "n_responders": <int — number of Responder (R) patients in the analysis cohort; null if not stated>,
  "n_nonresponders": <int — number of Non-Responder (NR) patients; null if not stated>,
  "median_R_TotalNonSyn": <float — median TotalNonSyn mutation count among Responders; null if not stated>,
  "median_NR_TotalNonSyn": <float — median TotalNonSyn mutation count among Non-Responders; null if not stated>,
  "mann_whitney_u_statistic": <float — Mann-Whitney U test statistic; null if not stated>,
  "mann_whitney_p_value": <float — p-value from the Mann-Whitney U test on TMB vs Response; null if not stated>,
  "spearman_p_value": <float — p-value from Spearman correlation if also computed; null if not stated>,
  "tmb_call": <"yes" | "no" | "borderline" — agent's final conclusion about TMB being significantly associated with response>,
  "statistical_test_used": <string — short name of the primary test (e.g., "Mann-Whitney U", "t-test", "Spearman")>,
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
