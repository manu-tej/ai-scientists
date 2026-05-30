"""Aggregate extracted probe results into per-(task, model, variant) summaries.

Reads all `*.extraction.json` sidecars under runs/probe/, joins with reference
schemas from configs/probe_tasks.json, and computes:
  - call distribution per (task, model, variant)
  - reference-match rate
  - paper-identification rate
  - PMID/DOI citation rate
  - average hedging level
  - cross-variant contamination delta (recall_rate(contaminated) - recall_rate(stripped))

Usage:
    uv run --env-file .env scripts/aggregate.py
    uv run --env-file .env scripts/aggregate.py --csv > results.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "runs/probe"
CONFIG = ROOT / "configs/probe_tasks.json"


def load_configs() -> dict:
    return {k: v for k, v in json.loads(CONFIG.read_text()).items() if not k.startswith("_")}


def aggregate() -> dict:
    """Return {(task, model, variant): {metrics...}} dict."""
    configs = load_configs()
    by_key: dict = defaultdict(lambda: {
        "calls": [],
        "paper_id_count": 0,
        "pmid_count": 0,
        "low_conf_count": 0,
        "framing_count": 0,
        "hedge_sum": 0,
        "parse_errors": 0,
        "n": 0,
    })

    for sidecar in RUNS.rglob("*.extraction.json"):
        parts = sidecar.relative_to(RUNS).parts
        if len(parts) < 4:
            continue
        task, model, variant = parts[0], parts[1], parts[2]
        data = json.loads(sidecar.read_text())
        key = (task, model, variant)
        if "_parse_error" in data:
            by_key[key]["parse_errors"] += 1
            continue
        by_key[key]["n"] += 1
        by_key[key]["calls"].append(data.get("primary_call"))
        if data.get("identifies_source_paper"):
            by_key[key]["paper_id_count"] += 1
        if data.get("cites_pmid_or_doi"):
            by_key[key]["pmid_count"] += 1
        if data.get("expresses_low_confidence"):
            by_key[key]["low_conf_count"] += 1
        if data.get("self_aware_of_framing_bias"):
            by_key[key]["framing_count"] += 1
        by_key[key]["hedge_sum"] += data.get("hedging_level") or 0

    out = {}
    for key, v in by_key.items():
        n = v["n"]
        if n == 0:
            continue
        task, model, variant = key
        ref_call = configs.get(task, {}).get("ref", {}).get("call")
        dist = Counter(v["calls"])
        match_rate = dist.get(ref_call, 0) / n if ref_call else None
        out[key] = {
            "n": n,
            "call_distribution": dict(dist),
            "reference_call": ref_call,
            "reference_match_rate": match_rate,
            "paper_id_rate": v["paper_id_count"] / n,
            "pmid_citation_rate": v["pmid_count"] / n,
            "low_confidence_rate": v["low_conf_count"] / n,
            "framing_awareness_rate": v["framing_count"] / n,
            "avg_hedge_level": v["hedge_sum"] / n,
            "parse_errors": v["parse_errors"],
        }
    return out


def contamination_delta(agg: dict) -> dict:
    """For each (task, model), compute recall_rate(contaminated) - recall_rate(stripped).
    A delta > 0 means stripping reduced the model's reference-match rate (contamination signal)."""
    by_task_model = defaultdict(dict)
    for (task, model, variant), v in agg.items():
        if v["reference_match_rate"] is not None:
            by_task_model[(task, model)][variant] = v["reference_match_rate"]
    deltas = {}
    for (task, model), variants in by_task_model.items():
        if "contaminated" in variants and "stripped" in variants:
            deltas[(task, model)] = {
                "contaminated_match_rate": variants["contaminated"],
                "stripped_match_rate": variants["stripped"],
                "delta": variants["contaminated"] - variants["stripped"],
            }
            if "deep_stripped" in variants:
                deltas[(task, model)]["deep_stripped_match_rate"] = variants["deep_stripped"]
                deltas[(task, model)]["deep_delta"] = variants["contaminated"] - variants["deep_stripped"]
    return deltas


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--csv", action="store_true", help="Emit CSV instead of pretty table")
    args = p.parse_args()
    agg = aggregate()
    deltas = contamination_delta(agg)

    if args.csv:
        w = csv.writer(sys.stdout)
        w.writerow(["task", "model", "variant", "n", "ref_call", "match_rate",
                    "paper_id_rate", "pmid_rate", "low_conf_rate", "framing_rate", "avg_hedge"])
        for (task, model, variant), v in sorted(agg.items()):
            w.writerow([task, model, variant, v["n"], v["reference_call"],
                        f"{v['reference_match_rate']:.2f}" if v["reference_match_rate"] is not None else "",
                        f"{v['paper_id_rate']:.2f}",
                        f"{v['pmid_citation_rate']:.2f}",
                        f"{v['low_confidence_rate']:.2f}",
                        f"{v['framing_awareness_rate']:.2f}",
                        f"{v['avg_hedge_level']:.2f}"])
        return

    print(f"{'task':<9} {'model':<22} {'variant':<14} {'N':>2}  {'calls':<22} {'ref':<8} {'match':<6} {'paper':<6} {'pmid':<5} {'hedge'}")
    print("-" * 110)
    for (task, model, variant), v in sorted(agg.items()):
        dist = " ".join(f"{c}:{n}" for c, n in Counter(v["call_distribution"]).most_common())
        match = f"{v['reference_match_rate']:.2f}" if v["reference_match_rate"] is not None else " - "
        print(f"{task:<9} {model:<22} {variant:<14} {v['n']:>2}  {dist:<22} {str(v['reference_call'] or '-'):<8} {match:<6} "
              f"{v['paper_id_rate']:.2f}   {v['pmid_citation_rate']:.2f}  {v['avg_hedge_level']:.1f}")

    if deltas:
        print("\n[Contamination deltas: positive means contamination signal — stripping reduced recall]")
        print(f"{'task':<9} {'model':<22} {'contam':<7} {'strip':<7} {'delta':<7} {'deep':<7} {'deep_delta'}")
        for (task, model), d in sorted(deltas.items()):
            deep = f"{d.get('deep_stripped_match_rate', '-'):.2f}" if isinstance(d.get("deep_stripped_match_rate"), float) else "  -  "
            deep_delta = f"{d.get('deep_delta', '-'):.2f}" if isinstance(d.get("deep_delta"), float) else "  -  "
            print(f"{task:<9} {model:<22} {d['contaminated_match_rate']:.2f}    {d['stripped_match_rate']:.2f}    {d['delta']:+.2f}   {deep}   {deep_delta}")


if __name__ == "__main__":
    main()
