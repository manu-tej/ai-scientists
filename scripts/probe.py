"""Unified contamination + consistency probe.

Runs both contaminated and stripped variants K times each on a given task,
captures predictions, and reports per-variant call distribution + numeric spread.

Usage:
    uv run --env-file .env scripts/probe.py --task da-3-4 --k 5
"""
from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

from anthropic import Anthropic
from dotenv import load_dotenv
from rich.console import Console

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODEL = "claude-opus-4-7"
CONFIG_FILE = ROOT / "configs/probe_tasks.json"

PREDICT_PROMPT = """You are an expert biomedical researcher. Below is a research task description.

WITHOUT running any code, downloading any data, or performing any actual analysis,
predict what the answer would be based on your existing knowledge of published research.

If this looks like a study or analysis you can recall, state your best prediction with
specific numerical values (e.g., HR, p-value) if you remember them.
If you cannot predict the answer with any confidence, state that explicitly.

Output your prediction in the format the task requests.

TASK:
{task}
"""

# Task-specific stripping rules and parsing references
TASK_CONFIG = {
    "da-12-4": {
        "strip": [
            ("Noncoding RNAs in Lung Adenocarcinoma", "Survival Analysis"),
            (r"(?i)lung cancer patients", "cancer cohort patients"),
            (r"(?i)lung adenocarcinoma", "cancer cohort"),
            ("TCGA_RNA-01A.csv", "cohort_rna.csv"),
            ("TCGA_microbiota-01A.csv", "cohort_microbiome.csv"),
            (r"\bTCGA[_\-]?\w*", "cohort"),
            ("NAR_Q3 folder", "data folder"),
            ("NAR_Q3", "uploaded"),
        ],
        "ref": {"call": "yes", "HR": 1.0124, "p": 0.0234},
        "entity": "kocuria",
    },
    "da-17-1": {
        "strip": [
            (r'"Single-cell RNA-seq reveals cell type[^"]*lupus"', "an SLE-PBMC scRNA-seq study"),
            ("Science 2022", "the source publication"),
            (r"4118e166[-\w]+", "STUDY_DATASET_ID"),
            (r"4118e166-[a-f0-9]+-[a-f0-9]+-[a-f0-9]+-[a-f0-9]+\.h5ad", "study_pbmc.h5ad"),
            (r"CZI CELLxGENE dataset UUID `[^`]+`", "a public scRNA-seq deposit"),
            ("162 SLE cases + 99 healthy controls", "an SLE-vs-control cohort"),
            (r"~1\.26M peripheral-blood mononuclear cells", "PBMCs"),
        ],
        # Reference per the rubric: 8 cell types altered.
        # Up: cM (~1.71x), Prolif (~3.10x), ncM (~1.59x), T8 (~1.24x),
        # B (~1.26x), PB (~1.70x).  Down: T4 (~0.73x), pDC (~0.61x).
        "ref": {
            "call": "yes",
            "expected_up": ["cM", "Prolif", "ncM", "T8", "B", "PB"],
            "expected_down": ["T4", "pDC"],
        },
        "entity": "cell",
    },
    "da-3-4": {
        "strip": [
            (r"(?i)hugo et al\.? 2016", "an earlier study"),
            (r"(?i)hugo et al\.?,? \(?cell 2016\)?", "an earlier study"),
            ("GSE78220", "the cohort"),
            (r"(?i)melanoma anti-pd-1", "cancer immunotherapy"),
            (r"(?i)melanoma", "tumor"),
            ("Cell 2016", "the source publication"),
            (r"(?i)irRECIST", "RECIST"),
        ],
        # Deep-strip removes the structural giveaways:
        # the S1A-S1E sheet-label signature, the supplementary_tables.xls
        # filename convention, and melanoma-specific marker gene mentions.
        "deep_strip": [
            (r"(?i)hugo et al\.? 2016", "an earlier study"),
            (r"(?i)hugo et al\.?,? \(?cell 2016\)?", "an earlier study"),
            ("GSE78220", "the cohort"),
            (r"(?i)melanoma anti-pd-1", "cancer immunotherapy"),
            (r"(?i)melanoma", "tumor"),
            ("Cell 2016", "the source publication"),
            (r"(?i)irRECIST", "RECIST"),
            ("supplementary_tables.xls", "study_tables.xls"),
            # Rename S1A..S1E -> sheet_a..sheet_e (case insensitive).
            (r"\bS1A\b", "sheet_a"),
            (r"\bS1B\b", "sheet_b"),
            (r"\bS1C\b", "sheet_c"),
            (r"\bS1D\b", "sheet_d"),
            (r"\bS1E\b", "sheet_e"),
            # Strip the melanoma-driver-gene list that telegraphs the paper.
            (r"BRAF/NRAS/NF1 mutation status, ?", ""),
            (r"mutation spectrum fractions \(A>G, C>T, etc.\)", "spectrum fractions"),
            # 'WES cohort from ... anti-PD-1 study' header line.
            (r"(?i)WES cohort from [^,]+,? ", "WES cohort, "),
        ],
        # Reference: per the paper / BiomniBench rubric the conclusion is
        # NO significant association at alpha=0.05 (small cohort underpowered).
        "ref": {"call": "no", "HR": None, "p_below_alpha": False},
        "entity": "tmb",
    },
}


def apply_strip(text: str, rules: list) -> str:
    """Apply strip rules. Each rule is either a (pattern, replace) tuple
    (legacy in-code config) or a {"pattern": ..., "replace": ...} dict
    (JSON config)."""
    out = text
    for rule in rules:
        if isinstance(rule, dict):
            pat, repl = rule["pattern"], rule["replace"]
        else:
            pat, repl = rule
        out = re.sub(pat, repl, out)
    return out


def load_task_configs() -> dict:
    """Prefer the external JSON config; fall back to TASK_CONFIG in code."""
    if CONFIG_FILE.exists():
        data = json.loads(CONFIG_FILE.read_text())
        # Drop the documentation-only schema key.
        return {k: v for k, v in data.items() if not k.startswith("_")}
    return TASK_CONFIG


def parse_call(response: str) -> str:
    """Yes / No / ambiguous on whether the agent predicts significance."""
    text = response.lower()
    # Patterns matching positive call
    yes_pat = [
        r"yes[^\n]{0,80}(significant|associated|poor prognosis)",
        r"is significantly (?:associated|correlated)",
        r"shows significant",
        r"hr ?> ?1 ?(?:and|,)? ?p ?< ?0\.05",
        r"reaches significance",
    ]
    no_pat = [
        r"\bno[^\n]{0,80}(not significant|not associated|no significant)",
        r"not significantly (?:associated|correlated)",
        r"no significant (?:association|correlation|difference)",
        r"does not reach significance",
        r"underpowered",
        r"p ?[>≥] ?0\.05",
    ]
    yes = any(re.search(p, text) for p in yes_pat)
    no = any(re.search(p, text) for p in no_pat)
    if yes and not no:
        return "yes"
    if no and not yes:
        return "no"
    if yes and no:
        return "mixed"
    return "ambiguous"


def parse_numeric(response: str, entity: str) -> dict:
    text = response.lower()
    # Look for HR and p in the same line as the entity
    near = re.search(
        rf"{entity}[^\n]*?(?:hr|hazard[ -]?ratio)[^\d]{{0,8}}(\d+\.\d+)[^\n]*?p[^\d]{{0,10}}(\d+\.\d+)",
        text,
    )
    hr, p = (float(near.group(1)), float(near.group(2))) if near else (None, None)
    # Fallback: any HR / p in text
    all_hrs = [float(v) for v in re.findall(r"hr[^\d\n]{0,8}(\d+\.\d+)", text)]
    all_ps = [float(v) for v in re.findall(r"\bp[ -]?(?:value)?[^\d\n]{0,8}(\d+\.\d+)", text)]
    return {"hr": hr, "p": p, "all_hrs": all_hrs, "all_ps": all_ps}


def run_one(client: Anthropic, model: str, prompt: str) -> tuple[str, int, int]:
    msg = client.messages.create(
        model=model, max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )
    return ("".join(b.text for b in msg.content if hasattr(b, "text")),
            msg.usage.input_tokens, msg.usage.output_tokens)


def main() -> None:
    configs = load_task_configs()
    p = argparse.ArgumentParser()
    p.add_argument("--task", required=True, choices=list(configs))
    p.add_argument("--k", type=int, default=5)
    p.add_argument("--variants", nargs="+", default=["contaminated", "stripped"])
    p.add_argument("--model", default=DEFAULT_MODEL)
    args = p.parse_args()

    load_dotenv()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("ANTHROPIC_API_KEY missing")
    console = Console()
    client = Anthropic()
    cfg = configs[args.task]
    task_dir = ROOT / f"data/biomnibench-da/{args.task}"
    model_slug = args.model.replace(".", "").replace("-", "_")
    model_dir = ROOT / f"runs/probe/{args.task}/{model_slug}"
    model_dir.mkdir(parents=True, exist_ok=True)

    original = (task_dir / "instruction.md").read_text()
    stripped = apply_strip(original, cfg["strip"])
    variant_texts = {"contaminated": original, "stripped": stripped}
    if "deep_strip" in cfg:
        variant_texts["deep_stripped"] = apply_strip(original, cfg["deep_strip"])

    variant_summaries: dict = {}
    for v in args.variants:
        console.print(f"\n[cyan]==> {v} (K={args.k})[/]")
        # Per-variant subdir so re-runs of one variant don't clobber another.
        vdir = model_dir / v
        vdir.mkdir(parents=True, exist_ok=True)
        prompt = PREDICT_PROMPT.format(task=variant_texts[v])
        (vdir / "prompt.txt").write_text(prompt)

        calls, hrs, ps = [], [], []
        runs: list[dict] = []
        for i in range(1, args.k + 1):
            text, in_tok, out_tok = run_one(client, args.model, prompt)
            (vdir / f"run_{i:02d}.txt").write_text(text)
            call = parse_call(text)
            num = parse_numeric(text, cfg["entity"])
            calls.append(call)
            if num["hr"] is not None:
                hrs.append(num["hr"])
            if num["p"] is not None:
                ps.append(num["p"])
            runs.append({"call": call, "hr": num["hr"], "p": num["p"], "in": in_tok, "out": out_tok})
            console.print(f"  [{i}] call={call:<9} hr={num['hr']}  p={num['p']}")

        ref_call = cfg["ref"].get("call")
        match_rate = calls.count(ref_call) / args.k if ref_call else None
        variant_summary = {
            "task": args.task,
            "model": args.model,
            "variant": v,
            "k": args.k,
            "reference": cfg["ref"],
            "ts": datetime.now(timezone.utc).isoformat(),
            "runs": runs,
            "calls": calls,
            "call_distribution": {c: calls.count(c) for c in set(calls)},
            "match_reference_call_rate": match_rate,
            "hr_values": hrs,
            "hr_mean": statistics.mean(hrs) if hrs else None,
            "hr_stdev": statistics.stdev(hrs) if len(hrs) > 1 else None,
            "p_values": ps,
            "p_mean": statistics.mean(ps) if ps else None,
            "p_stdev": statistics.stdev(ps) if len(ps) > 1 else None,
            "tokens": {
                "input_total": sum(r["in"] for r in runs),
                "output_total": sum(r["out"] for r in runs),
            },
        }
        (vdir / "summary.json").write_text(json.dumps(variant_summary, indent=2))
        variant_summaries[v] = variant_summary

    # Cross-variant aggregate at the model level (also rewritten each run).
    aggregate = {
        "task": args.task,
        "model": args.model,
        "k": args.k,
        "ts": datetime.now(timezone.utc).isoformat(),
        "variants": {v: {k: vs[k] for k in ("call_distribution", "match_reference_call_rate", "tokens")}
                     for v, vs in variant_summaries.items()},
    }
    (model_dir / "aggregate.json").write_text(json.dumps(aggregate, indent=2))

    console.print("\n[bold]Summary[/]")
    for v, vs in variant_summaries.items():
        console.print(f"  {v:<14} calls={vs['call_distribution']}  match_ref={vs['match_reference_call_rate']}")
    if cfg["ref"].get("call"):
        console.print(f"  [yellow]Reference call: {cfg['ref']['call']}[/]")
    console.print(f"\n[green]done[/] -> {model_dir}/")


if __name__ == "__main__":
    main()
