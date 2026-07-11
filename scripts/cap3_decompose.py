#!/usr/bin/env python3
"""Per-replicate delivery decomposition for the BiomniBench-DA capability matrix.

The MiniMax-3 grade files give a 3-rep median per (agent, task). This decomposes each
median into its 3 actual replicate traces in the CANONICAL run tree `runs/cap3/` (the full
450 = 3 agents x 50 tasks x 3 reps, fetched from remote:~/benchbench/runs/cap3) and flags
whether every rep actually delivered a real answer — so a low median can be read as genuine
low-quality work vs a non-delivery floor.

Canonical sources (do NOT use runs/harbor_base_matrix — it is a partial copy with
rate-limited replicates that masquerade as non-deliveries):
    grades : results/biomnibench/grades/biomni_{cc,codex,agy}_minimax.json   (score of record)
    traces : runs/cap3/{claude-code,codex,antigravity-cli}/<task>/<ts>/<task>__<hash>/artifacts/

Usage:
    python scripts/cap3_decompose.py                # all failing cells (median < 0.55)
    python scripts/cap3_decompose.py --threshold 1  # all cells
    python scripts/cap3_decompose.py --json out.json
"""
from __future__ import annotations

import argparse
import glob
import json
import os

HARNESS = {"cc": "claude-code", "codex": "codex", "agy": "antigravity-cli"}
GRADE = "results/biomnibench/grades/biomni_{a}_minimax.json"
CAP3 = "runs/cap3/{h}"
EMPTY_BYTES = 80  # answer.txt below this is a non-delivery / refusal-stub


def rep_artifact(agent: str, rep_id: str, name: str) -> str | None:
    """Path to a cap3 artifact (answer.txt / trace.md) for a graded rep id like da-1-3__C9ZBzcS."""
    hits = glob.glob(f"{CAP3.format(h=HARNESS[agent])}/*/*/{rep_id}/artifacts/{name}")
    return hits[0] if hits else None


def size(path: str | None) -> int | None:
    return os.path.getsize(path) if path and os.path.exists(path) else None


def decompose(threshold: float):
    rows = []
    for agent in ("cc", "codex", "agy"):
        for cell in json.load(open(GRADE.format(a=agent))):
            if cell["median"] >= threshold:
                continue
            reps = []
            for r in cell["reps"]:
                ans = size(rep_artifact(agent, r["rep"], "answer.txt"))
                trc = size(rep_artifact(agent, r["rep"], "trace.md"))
                reps.append({
                    "rep": r["rep"], "norm": r["norm"],
                    "answer_bytes": ans, "trace_bytes": trc,
                    "delivered": ans is not None and ans >= EMPTY_BYTES,
                })
            n_expected = len(cell["reps"])
            n_real = sum(1 for r in reps if r["delivered"])
            n_traced = sum(1 for r in reps if r["answer_bytes"] is not None)
            rows.append({
                "agent": agent, "task": cell["task"], "median": cell["median"],
                "norms": cell["norms"], "reps": reps,
                "all_delivered": n_real == n_expected and n_traced == n_expected,
                "n_real": n_real, "n_expected": n_expected,
                "verdict": ("all_real" if n_real == n_expected
                            else "non_delivery" if n_real == 0
                            else f"partial_{n_real}of{n_expected}"),
            })
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--threshold", type=float, default=0.55, help="report cells with median < threshold")
    ap.add_argument("--json", help="write structured rows to this path")
    args = ap.parse_args()

    rows = decompose(args.threshold)
    print(f"{'agent/task':16} {'norms':>22} {'answer.txt bytes':>22}  verdict")
    for r in rows:
        szs = str([rep["answer_bytes"] if rep["answer_bytes"] is not None else "NA" for rep in r["reps"]])
        print(f"{r['agent'] + '/' + r['task']:16} {str(r['norms']):>22} {szs:>22}  {r['verdict']}")

    n = len(rows)
    clean = sum(1 for r in rows if r["all_delivered"])
    nondel = [f"{r['agent']}/{r['task']}" for r in rows if r["verdict"] != "all_real"]
    print(f"\n{n} cells | all-3-reps-delivered: {clean}/{n} | NOT all-real: {nondel or 'none'}")

    if args.json:
        json.dump(rows, open(args.json, "w"), indent=1)
        print(f"wrote {args.json}")


if __name__ == "__main__":
    main()
