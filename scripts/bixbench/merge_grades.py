#!/usr/bin/env python3
"""Combine per-agent BixBench grade JSONs into per-agent and cross-agent summaries.

Takes one or more grade JSONs per agent (e.g. the 15-task subset + the 35-task full
set) and reports, per agent, the mean over all tasks of:
  open  (open-answer accuracy)   mcq  (MCQ accuracy)   consist (run-to-run agreement)
Also lists every task where ALL agents fail open (open_acc == 0) — the candidate
gold/verifier-artifact or correlated-cross-agent-failure tasks worth auditing.

Usage:
  python scripts/bixbench/merge_grades.py \
      --agent cc    runs/bixbench_subset_claude-code_grade_v2.json runs/bixbench_full_claude-code_grade.json \
      --agent codex runs/bixbench_subset_codex_grade_v2.json       runs/bixbench_full_codex_grade.json \
      --agent agy   runs/bixbench_subset_antigravity-cli_grade_v2.json runs/bixbench_full_antigravity-cli_grade.json \
      --out runs/bixbench_full50_summary.json
"""
from __future__ import annotations
import argparse, json
from pathlib import Path


def load_tasks(paths: list[Path]) -> dict[str, dict]:
    """Merge several grade JSONs into one {task_id: record} map (later files win)."""
    tasks: dict[str, dict] = {}
    for p in paths:
        for rec in json.loads(Path(p).read_text()):
            tasks[rec["task"]] = rec
    return tasks


def agg(tasks: dict[str, dict]) -> dict:
    pick = lambda key: [t[key] for t in tasks.values() if t.get(key) is not None]
    mean = lambda xs: round(sum(xs) / len(xs), 4) if xs else None
    return {"open": mean(pick("open_acc")), "mcq": mean(pick("mcq_acc")),
            "consist": mean(pick("open_agree")), "n": len(tasks)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--agent", action="append", nargs="+", metavar=("NAME", "GRADE_JSON"),
                    required=True, help="agent label followed by its grade JSON(s)")
    ap.add_argument("--out", type=Path, help="write the summary JSON here")
    args = ap.parse_args()

    per_agent = {a[0]: load_tasks([Path(p) for p in a[1:]]) for a in args.agent}
    summary = {name: agg(tasks) for name, tasks in per_agent.items()}

    all_tasks = sorted(set().union(*[set(t) for t in per_agent.values()]))
    all_fail = []
    for tid in all_tasks:
        vals = {a: per_agent[a][tid]["open_acc"] for a in per_agent if tid in per_agent[a]}
        if len(vals) == len(per_agent) and all(v == 0.0 for v in vals.values()):
            mode = next(per_agent[a][tid]["eval_mode"] for a in per_agent if tid in per_agent[a])
            all_fail.append({"task": tid, "eval_mode": mode})

    order = sorted(summary, key=lambda a: summary[a]["open"] or 0, reverse=True)
    print(f"{'agent':8} {'open':>7} {'mcq':>7} {'consist':>8} {'n':>4}")
    for a in order:
        s = summary[a]
        print(f"{a:8} {s['open']:>7} {s['mcq']:>7} {s['consist']:>8} {s['n']:>4}")
    print(f"\nALL-AGENTS-FAIL tasks ({len(all_fail)}):")
    for t in all_fail:
        print(f"  {t['task']:12} [{t['eval_mode']}]")

    if args.out:
        out = {"per_agent": summary, "all_agents_fail": all_fail}
        args.out.write_text(json.dumps(out, indent=2))
        print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
