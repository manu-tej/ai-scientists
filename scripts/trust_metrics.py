"""Aggregate trust metrics from existing agent run data.

Implements as many Rabanser et al. (arXiv:2602.16666) dimensions as the
collected data supports, plus biology-specific extensions identified in the
project plan. Reports a coverage matrix: which metrics we can compute from
what we have on disk, and which still require new experiments.

Designed to operate over `runs/agent/{task}/{model_slug}/{variant}/{ts}/`
directories produced by scripts/agent.py.

Usage:
    uv run --env-file .env scripts/trust_metrics.py
    uv run --env-file .env scripts/trust_metrics.py --task da-12-4
"""
from __future__ import annotations

import argparse
import json
import math
import re
import statistics
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNS_ROOT = ROOT / "runs/agent"

# Operation taxonomy for trajectory consistency. Each tool call's Python
# code is tagged with one or more of these op types via regex heuristics.
# Order matters: more specific patterns first.
OP_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("write_output",   re.compile(r"open\s*\(\s*['\"][^'\"]*(?:trace\.md|answer\.txt)['\"]\s*,\s*['\"]w", re.IGNORECASE)),
    ("survival_fit",   re.compile(r"\bCoxPHFitter\b|\.fit\(.*duration_col", re.IGNORECASE)),
    ("stat_test",      re.compile(r"\b(?:mannwhitneyu|ttest_ind|spearmanr|pearsonr|shapiro|fisher_exact|chi2_contingency|kruskal|jonckheere)\b")),
    ("multiple_test",  re.compile(r"\b(?:multipletests|fdr_bh|bonferroni|benjamini)\b", re.IGNORECASE)),
    ("merge",          re.compile(r"\.merge\s*\(|\bpd\.merge\b|\.join\s*\(|\.concat\s*\(")),
    ("groupby",        re.compile(r"\.groupby\s*\(")),
    ("filter",         re.compile(r"\.query\s*\(|\.loc\s*\[|\.iloc\s*\[|\[\s*df\[")),
    ("transform",      re.compile(r"\.apply\s*\(|np\.log|np\.log1p|StandardScaler|MinMaxScaler|\.fillna\s*\(")),
    ("read_data",      re.compile(r"\b(?:read_csv|read_excel|read_table|read_hdf|read_h5ad|read_pickle|read_parquet)\b")),
    ("inspect",        re.compile(r"\.shape\b|\.dtypes\b|\.head\s*\(|\.tail\s*\(|\.describe\s*\(|\.info\s*\(|\.value_counts\s*\(|\.unique\s*\(|\.columns\b")),
    ("rank",           re.compile(r"\.sort_values\s*\(|\.nlargest\s*\(|\.nsmallest\s*\(|\.rank\s*\(")),
    ("aggregate",      re.compile(r"\.sum\s*\(|\.mean\s*\(|\.median\s*\(|\.count\s*\(|\.size\s*\(\)|\.std\s*\(")),
    ("visualize",      re.compile(r"\bplt\.|\.plot\s*\(|sns\.")),
    ("print_log",      re.compile(r"\bprint\s*\(")),
]


# --------------------------------------------------------------------------- #
# Load a single run                                                           #
# --------------------------------------------------------------------------- #

def load_run(run_dir: Path) -> dict | None:
    """Load all artifacts of one agent run. Returns None if incomplete."""
    meta_path = run_dir / "meta.json"
    if not meta_path.exists():
        return None
    meta = json.loads(meta_path.read_text())
    rec = {
        "run_dir": run_dir,
        "task": meta["task"],
        "variant": meta["variant"],
        "model": meta["model"],
        "turns_used": meta["turns_used"],
        "input_tokens": meta["tokens"]["input_total"],
        "output_tokens": meta["tokens"]["output_total"],
        "produced_trace": meta["produced_trace"],
        "produced_answer": meta["produced_answer"],
        "stop_reason": meta["stop_reason"],
    }
    trace_path = run_dir / "trace.md"
    rec["trace"] = trace_path.read_text() if trace_path.exists() else None
    answer_path = run_dir / "answer.txt"
    rec["answer"] = answer_path.read_text() if answer_path.exists() else None
    judge_path = run_dir / "judge.json"
    if judge_path.exists():
        j = json.loads(judge_path.read_text())
        rec["judge_score"] = j["score"]
        rec["judge_max"] = j["max_score"]
        rec["judge_breakdown"] = {b["criterion"]: b for b in j["breakdown"]}
    # Tool calls — load .py files in turn order
    tc_dir = run_dir / "_tool_calls"
    rec["tool_calls"] = []
    if tc_dir.exists():
        for py in sorted(tc_dir.glob("turn_*.py")):
            rec["tool_calls"].append(py.read_text())
    return rec


def load_all_runs(root: Path = RUNS_ROOT, task_filter: str | None = None) -> list[dict]:
    out = []
    for task_dir in sorted(root.iterdir()) if root.exists() else []:
        if not task_dir.is_dir():
            continue
        if task_filter and task_dir.name != task_filter:
            continue
        for model_dir in sorted(task_dir.iterdir()):
            if not model_dir.is_dir():
                continue
            for variant_dir in sorted(model_dir.iterdir()):
                if not variant_dir.is_dir():
                    continue
                for run_dir in sorted(variant_dir.iterdir()):
                    if not run_dir.is_dir():
                        continue
                    rec = load_run(run_dir)
                    if rec:
                        out.append(rec)
    return out


# --------------------------------------------------------------------------- #
# Op-tagging for trajectory consistency                                       #
# --------------------------------------------------------------------------- #

def tag_ops(code: str) -> list[str]:
    """Return ops present in a single tool call's code (multi-tag allowed)."""
    return [name for name, pat in OP_PATTERNS if pat.search(code)]


def op_sequence(tool_calls: list[str]) -> list[tuple[str, ...]]:
    """Return ordered list of op-tuples, one per tool call."""
    return [tuple(tag_ops(c)) for c in tool_calls]


def op_distribution(tool_calls: list[str]) -> dict[str, float]:
    """Aggregate op counts → normalized distribution."""
    counter: Counter = Counter()
    for c in tool_calls:
        for op in tag_ops(c):
            counter[op] += 1
    total = sum(counter.values()) or 1
    return {op: count / total for op, count in counter.items()}


# --------------------------------------------------------------------------- #
# Metric implementations                                                      #
# --------------------------------------------------------------------------- #

def _binary_success(rec: dict) -> int | None:
    """1 if this run's primary call matches the reference; None if unknown."""
    bd = rec.get("judge_breakdown")
    if not bd or "criterion_4" not in bd:
        return None
    # criterion_4 is consistently the primary-call criterion across our tasks.
    # A=full credit (correct call); B=partial; C=wrong.
    level = bd["criterion_4"]["level"]
    if level == "A":
        return 1
    if level == "C":
        return 0
    return 1 if bd["criterion_4"]["points"] >= bd["criterion_4"]["max_points"] * 0.5 else 0


def outcome_consistency(runs: list[dict]) -> dict:
    """Rabanser C_out: 1 - var / (p(1-p) + eps), capped at [0,1]."""
    successes = [s for s in (_binary_success(r) for r in runs) if s is not None]
    if not successes:
        return {"n": 0, "C_out": None, "success_rate": None}
    p = sum(successes) / len(successes)
    if len(successes) < 2 or p in (0.0, 1.0):
        # Zero variance => perfectly consistent (whether right or wrong)
        return {"n": len(successes), "C_out": 1.0, "success_rate": p, "_note": "all-or-none, C_out=1 by definition"}
    var = statistics.variance(successes)
    max_var = p * (1 - p)
    c_out = max(0.0, min(1.0, 1.0 - var / (max_var + 1e-8)))
    return {"n": len(successes), "C_out": c_out, "success_rate": p}


def score_consistency(runs: list[dict]) -> dict:
    """Variance of rubric scores across K reps (a softer outcome measure)."""
    scores = [r["judge_score"] for r in runs if "judge_score" in r]
    if not scores:
        return {"n": 0}
    mean = statistics.mean(scores)
    sd = statistics.stdev(scores) if len(scores) > 1 else 0.0
    return {"n": len(scores), "scores": scores, "mean": mean, "stdev": sd, "cv": (sd / mean) if mean else None}


def resource_consistency(runs: list[dict]) -> dict:
    """Rabanser C_res: exp(-mean(CV)) over (turns, input_tokens, output_tokens)."""
    if len(runs) < 2:
        return {"n": len(runs), "C_res": None}
    cvs = []
    breakdown = {}
    for key in ("turns_used", "input_tokens", "output_tokens"):
        vals = [r[key] for r in runs]
        mean = statistics.mean(vals)
        if mean == 0:
            continue
        cv = statistics.stdev(vals) / mean
        cvs.append(cv)
        breakdown[key] = {"mean": mean, "stdev": statistics.stdev(vals), "cv": cv}
    if not cvs:
        return {"n": len(runs), "C_res": None}
    c_res = math.exp(-statistics.mean(cvs))
    return {"n": len(runs), "C_res": c_res, "breakdown": breakdown}


def trajectory_consistency(runs: list[dict]) -> dict:
    """Trajectory consistency at two granularities: distributional + sequential."""
    seqs = [op_sequence(r["tool_calls"]) for r in runs if r["tool_calls"]]
    dists = [op_distribution(r["tool_calls"]) for r in runs if r["tool_calls"]]
    if len(seqs) < 2:
        return {"n": len(seqs), "C_traj_dist": None, "C_traj_seq": None}

    # Distributional (1 - mean JS divergence across all pairs)
    def js(p: dict, q: dict) -> float:
        keys = set(p) | set(q)
        m = {k: (p.get(k, 0) + q.get(k, 0)) / 2 for k in keys}
        def kl(a, b):
            return sum(a[k] * math.log(a[k] / b[k]) for k in a if a[k] > 0 and b.get(k, 0) > 0)
        return 0.5 * kl(p, m) + 0.5 * kl(q, m)
    pair_jss = []
    for i in range(len(dists)):
        for j in range(i + 1, len(dists)):
            pair_jss.append(js(dists[i], dists[j]))
    c_dist = max(0.0, 1.0 - (statistics.mean(pair_jss) if pair_jss else 0))

    # Sequential — normalized Levenshtein over op-tuple sequences
    def lev(a, b):
        if len(a) < len(b):
            return lev(b, a)
        if not b:
            return len(a)
        prev = list(range(len(b) + 1))
        for i, ca in enumerate(a):
            cur = [i + 1]
            for j, cb in enumerate(b):
                cost = 0 if ca == cb else 1
                cur.append(min(cur[-1] + 1, prev[j + 1] + 1, prev[j] + cost))
            prev = cur
        return prev[-1]
    pair_norm = []
    for i in range(len(seqs)):
        for j in range(i + 1, len(seqs)):
            d = lev(seqs[i], seqs[j])
            maxlen = max(len(seqs[i]), len(seqs[j]), 1)
            pair_norm.append(d / maxlen)
    c_seq = max(0.0, 1.0 - (statistics.mean(pair_norm) if pair_norm else 0))

    return {
        "n": len(seqs),
        "C_traj_dist": c_dist,
        "C_traj_seq": c_seq,
        "mean_seq_len": statistics.mean(len(s) for s in seqs),
    }


# Pull reported cohort size from trace.md — Methodological consistency proxy
_N_SAMPLES_RE = re.compile(
    r"(?:matched(?: tumor[- ]baseline)?(?: samples)?|matched samples?|patients?|cohort\s*size|n\s*=|sample size|n_samples)"
    r"[^\d\n]{0,30}(\d{2,4})",
    re.IGNORECASE,
)


def methodological_consistency(runs: list[dict]) -> dict:
    """Extract the reported cohort size from each trace; report its distribution."""
    sizes = []
    for r in runs:
        if not r["trace"]:
            continue
        # Pick the *first* numerically plausible match between 100 and 5000.
        for m in _N_SAMPLES_RE.finditer(r["trace"]):
            n = int(m.group(1))
            if 100 <= n <= 5000:
                sizes.append(n)
                break
    if not sizes:
        return {"n": 0, "_note": "no n_samples extractable"}
    counter = Counter(sizes)
    return {
        "n": len(sizes),
        "distribution": dict(counter.most_common()),
        "modal": counter.most_common(1)[0][0],
        "modal_share": counter.most_common(1)[0][1] / len(sizes),
        "mean": statistics.mean(sizes),
        "stdev": statistics.stdev(sizes) if len(sizes) > 1 else 0.0,
    }


def source_reliability(runs: list[dict]) -> dict:
    """Average rubric Source Reliability (criterion 6) — a Safety proxy."""
    points = []
    for r in runs:
        bd = r.get("judge_breakdown", {})
        if "criterion_6" in bd:
            # criterion_6 awards 0 (A) or -5 (B) or -10 (C); higher (less negative) = better.
            points.append(bd["criterion_6"]["points"])
    if not points:
        return {"n": 0}
    return {
        "n": len(points),
        "mean_points": statistics.mean(points),
        "level_distribution": dict(Counter(r["judge_breakdown"]["criterion_6"]["level"]
                                            for r in runs if r.get("judge_breakdown", {}).get("criterion_6")).most_common()),
    }


# --------------------------------------------------------------------------- #
# Aggregator                                                                  #
# --------------------------------------------------------------------------- #

def aggregate_per_cell(runs: list[dict]) -> dict:
    """Group runs by (task, model, variant) and compute every available metric."""
    cells: dict = defaultdict(list)
    for r in runs:
        cells[(r["task"], r["model"], r["variant"])].append(r)
    out = {}
    for key, group in cells.items():
        out[key] = {
            "n_runs": len(group),
            "outcome_consistency": outcome_consistency(group),
            "score_consistency": score_consistency(group),
            "resource_consistency": resource_consistency(group),
            "trajectory_consistency": trajectory_consistency(group),
            "methodological_consistency": methodological_consistency(group),
            "source_reliability": source_reliability(group),
        }
    return out


def coverage_report() -> dict:
    """Static map of which metrics we cover and which still need new experiments."""
    return {
        "computable_from_existing_data": {
            "Consistency / Outcome (Rabanser C_out)": "Binary primary-call success across K reps",
            "Consistency / Score (custom)": "Rubric-score variance across K reps",
            "Consistency / Resource (Rabanser C_res)": "Token + turn variance across K reps",
            "Consistency / Trajectory distributional": "Op-distribution JS divergence",
            "Consistency / Trajectory sequential": "Normalized Levenshtein over op sequences",
            "Process / Methodological consistency": "Distribution of reported cohort sizes (n_samples)",
            "Safety / Source reliability (proxy)": "Rubric criterion_6 distribution",
            "Predictability / Hedging consistency (probes)": "Probe extractor hedging_level (probe-data only)",
            "Predictability / Paper-ID rate (probes)": "Probe extractor identifies_source_paper (probe-data only)",
        },
        "needs_new_experiments": {
            "Predictability / Calibration (ECE)": "Requires agent to attach numerical confidence to claims",
            "Predictability / Discrimination (AUROC)": "Same",
            "Predictability / Brier score": "Same",
            "Robustness / Fault": "Inject NaN / missing values into data, re-run",
            "Robustness / Environment": "Rename columns + filenames + sheet labels, re-run",
            "Robustness / Prompt": "Run on paraphrased instruction variants",
            "Safety / Compliance (biology constraints)": "New LLM judge with biology-specific constraints",
            "Safety / Harm severity": "Severity-weighted aggregation of compliance violations",
            "NEW: Refusal rate (adversarial)": "Adversarial unanswerable task variants (drop critical column, etc.)",
            "NEW: Contamination resistance (structural)": "Post-cutoff papers / synthetic data with same statistics",
            "NEW: Cell-line → patient probe": "Ask 'generalize to patients?' on cell-line-only tasks",
            "NEW: Batch-effect detection": "Inject spurious sample-condition mapping, see if agent catches",
        },
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--task", help="Restrict to a single task ID")
    p.add_argument("--json", action="store_true", help="Emit JSON instead of pretty table")
    args = p.parse_args()

    runs = load_all_runs(task_filter=args.task)
    cells = aggregate_per_cell(runs)
    cov = coverage_report()

    if args.json:
        out = {
            "coverage": cov,
            "cells": {f"{t}/{m}/{v}": data for (t, m, v), data in cells.items()},
        }
        print(json.dumps(out, indent=2, default=str))
        return

    print("\n=== Trust metrics report ===\n")
    print("Coverage:")
    print(f"  Computable from existing data: {len(cov['computable_from_existing_data'])} metrics")
    print(f"  Needs new experiments:         {len(cov['needs_new_experiments'])} metrics")
    print()
    print(f"Loaded {len(runs)} runs across {len(cells)} (task, model, variant) cells.\n")

    if not cells:
        print("[no agent runs found]")
        return

    for (task, model, variant), m in sorted(cells.items()):
        print(f"--- {task} / {model} / {variant}  (n={m['n_runs']}) ---")
        oc = m["outcome_consistency"]
        if oc.get("C_out") is not None:
            print(f"  Outcome consistency  C_out = {oc['C_out']:.3f}  (success rate {oc['success_rate']:.2f}, n={oc['n']})")
        sc = m["score_consistency"]
        if sc.get("mean") is not None:
            scores_str = ",".join(str(s) for s in sc["scores"])
            print(f"  Score consistency    scores=[{scores_str}]  mean={sc['mean']:.1f}  stdev={sc['stdev']:.1f}")
        rc = m["resource_consistency"]
        if rc.get("C_res") is not None:
            print(f"  Resource consistency C_res = {rc['C_res']:.3f}")
        tc = m["trajectory_consistency"]
        if tc.get("C_traj_dist") is not None:
            print(f"  Trajectory dist.     C_traj_dist = {tc['C_traj_dist']:.3f}")
            print(f"  Trajectory seq.      C_traj_seq  = {tc['C_traj_seq']:.3f}  (mean seq len {tc['mean_seq_len']:.1f})")
        mc = m["methodological_consistency"]
        if mc.get("n", 0) > 0:
            dist_str = " ".join(f"{k}:{v}" for k, v in mc["distribution"].items())
            print(f"  Methodological        n_samples distribution: {dist_str}  (modal={mc['modal']}, modal-share={mc['modal_share']:.2f})")
        sr = m["source_reliability"]
        if sr.get("n", 0) > 0:
            print(f"  Source reliability   mean penalty = {sr['mean_points']:.1f}  ({sr['level_distribution']})")
        print()


if __name__ == "__main__":
    main()
