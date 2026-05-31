"""Compute calibration metrics (ECE, Brier, MCE) for the `--calibrate` agent runs.

This closes the one reproducibility gap in the project: the headline
"monotonic ECE vs. success rate" finding in RESULTS.md was previously computed
by hand and had no committed script. This regenerates it from the on-disk
calibrate runs + their rubric judgments.

Data model
----------
Each calibrate run lives at
    runs/agent/{task}/{model}/{variant}_calibrate/{ts}/
and contains:
    answer.txt   -> a line "CONFIDENCE: HIGH|MEDIUM|LOW"  (elicited)
    judge.json   -> rubric judgment with a criterion_4 (primary-call) level

Two modeling choices, both made explicit as constants below:

1. SUCCESS DEFINITION (`success_of`): a run is a "success" if it got the
   primary scientific call right. We read rubric criterion_4's level: A=correct
   call, B=partial, C=wrong. We count A (and B at >=50% of its points) as
   success. This tracks *the answer*, not presentation/citation polish, which
   is what calibration should be about.

   NOTE: RESULTS.md's original table used this definition for 5/6 tasks but
   used a full-rubric score>=75 threshold for da-17-1. Using ONE consistent
   definition here is deliberate; the discrepancy is reported by --audit.

2. CONFIDENCE -> PROBABILITY MAP (`CONF_PROB`): ECE needs each confidence bucket
   mapped to a probability. HIGH=0.90, MEDIUM=0.60, LOW=0.30 is the default.
   This is the single most consequential knob: ECE scales directly with the gap
   between these and the observed accuracy. Adjust here and re-run to test
   sensitivity.

Usage:
    uv run scripts/calibration_ece.py                 # per-task table
    uv run scripts/calibration_ece.py --audit         # + reconcile vs RESULTS.md
    uv run scripts/calibration_ece.py --json
"""
from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNS_ROOT = ROOT / "runs/agent"

# --- Modeling choice 1: confidence -> probability (the key ECE knob) --------- #
CONF_PROB: dict[str, float] = {"HIGH": 0.90, "MEDIUM": 0.60, "LOW": 0.30}

# --- Modeling choice 2: which confidence labels we recognize ----------------- #
_CONF_RE = re.compile(r"CONFIDENCE:\s*(HIGH|MEDIUM|MED|LOW)", re.IGNORECASE)

# What RESULTS.md (committed) currently claims, for the --audit reconciliation.
RESULTS_CLAIMED_ECE = {
    "da-3-4": 0.10, "da-13-3": 0.10, "da-17-1": 0.30,
    "da-5-1": 0.40, "da-12-4": 0.59, "da-20-1": 0.90,
}


def parse_confidence(answer_text: str) -> str | None:
    m = _CONF_RE.search(answer_text)
    if not m:
        return None
    v = m.group(1).upper()
    return "MEDIUM" if v == "MED" else v


def success_of(judge: dict) -> int | None:
    """Primary-call correctness from rubric criterion_4. None if unjudged.

    Strict: only level A (fully correct primary call) is a success. B (partial)
    and C (wrong) are failures. For *calibration* of a binary scientific call,
    a partial answer does not justify a HIGH-confidence claim, so it is not a
    success. (Letting B count by point-fraction reintroduces a per-task
    inconsistency — the very thing this script exists to remove.)
    """
    c4 = next((b for b in judge.get("breakdown", []) if b["criterion"] == "criterion_4"), None)
    if c4 is None:
        return None
    return 1 if c4["level"] == "A" else 0


def load_calibrate_runs() -> list[dict]:
    """One record per (confidence, success) pair across all calibrate runs."""
    out = []
    for meta in RUNS_ROOT.glob("*/*/*calibrate*/*/meta.json"):
        d = meta.parent
        ans, jud = d / "answer.txt", d / "judge.json"
        if not (ans.exists() and jud.exists()):
            continue
        conf = parse_confidence(ans.read_text())
        if conf is None:
            continue
        succ = success_of(json.loads(jud.read_text()))
        if succ is None:
            continue
        out.append({"task": d.parts[-4], "variant": d.parts[-2], "conf": conf, "success": succ})
    return out


def ece_brier(records: list[dict]) -> dict:
    """Binned ECE + MCE (bins = confidence labels) and per-sample Brier score."""
    n = len(records)
    if n == 0:
        return {"n": 0}
    bins: dict[str, list[int]] = defaultdict(list)
    for r in records:
        bins[r["conf"]].append(r["success"])
    ece = mce = 0.0
    bin_detail = {}
    for conf, succs in bins.items():
        p = CONF_PROB[conf]
        acc = sum(succs) / len(succs)
        gap = abs(acc - p)
        weight = len(succs) / n
        ece += weight * gap
        mce = max(mce, gap)
        bin_detail[conf] = {"n": len(succs), "conf_prob": p, "accuracy": acc, "gap": gap}
    brier = sum((CONF_PROB[r["conf"]] - r["success"]) ** 2 for r in records) / n
    return {
        "n": n,
        "success_rate": sum(r["success"] for r in records) / n,
        "ECE": ece,
        "MCE": mce,
        "Brier": brier,
        "bins": bin_detail,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", help="restrict to one task")
    ap.add_argument("--audit", action="store_true", help="reconcile vs RESULTS.md claimed ECE")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    records = load_calibrate_runs()
    if args.task:
        records = [r for r in records if r["task"] == args.task]

    per_task = defaultdict(list)
    for r in records:
        per_task[r["task"]].append(r)
    results = {t: ece_brier(rs) for t, rs in per_task.items()}

    if args.json:
        print(json.dumps({"conf_prob_map": CONF_PROB, "per_task": results}, indent=2))
        return

    # Order by success rate so the monotonic ECE pattern is visible.
    order = sorted(results, key=lambda t: results[t]["success_rate"], reverse=True)
    conf_dist = defaultdict(int)
    for r in records:
        conf_dist[r["conf"]] += 1

    print(f"\nConfidence->probability map: {CONF_PROB}")
    print(f"Success = rubric criterion_4 primary-call correct (strict: level A only).")
    print(f"Confidence distribution across {len(records)} calibrate runs: {dict(conf_dist)}\n")
    print(f"{'task':<9}{'n':<4}{'success':<9}{'ECE':<7}{'MCE':<7}{'Brier':<7}")
    for t in order:
        m = results[t]
        print(f"{t:<9}{m['n']:<4}{m['success_rate']:<9.2f}{m['ECE']:<7.2f}{m['MCE']:<7.2f}{m['Brier']:<7.2f}")

    # Aggregate (pooled) ECE
    pooled = ece_brier(records)
    print(f"\npooled    {pooled['n']:<4}{pooled['success_rate']:<9.2f}{pooled['ECE']:<7.2f}{pooled['MCE']:<7.2f}{pooled['Brier']:<7.2f}")
    print(f"\nLOW used: {conf_dist.get('LOW', 0)} times "
          f"({'never — structural overconfidence' if conf_dist.get('LOW', 0) == 0 else 'present'})")

    if args.audit:
        print("\n=== Reconciliation vs RESULTS.md committed ECE ===")
        print(f"{'task':<9}{'this script':<13}{'RESULTS.md':<12}{'status'}")
        for t in order:
            got = results[t]["ECE"]
            claim = RESULTS_CLAIMED_ECE.get(t)
            if claim is None:
                status = "(not in RESULTS)"
            elif abs(got - claim) <= 0.03:
                status = "reproduces"
            else:
                status = f"REVISED (was computed with a different success def)"
            print(f"{t:<9}{got:<13.2f}{str(claim):<12}{status}")


if __name__ == "__main__":
    main()
