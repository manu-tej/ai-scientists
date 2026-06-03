"""Grade collected BASE-task agent traces with Gemini 3.1 Pro (Phylo's rubric judge).

Capability scoring for a collect-only base arm: reuses regrade_gemini.py's VERBATIM Phylo
prompt + level->points scoring (so this is Phylo's judge, just the Gemini model), but
iterates Harbor run dirs directly instead of a pre-built bundle. Reads each task's latest
run artifacts (answer.txt + trace.md) and the task rubric, asks Gemini to pick a level per
criterion, and sums to the Phylo score. Reports raw + normalized (score/max) per task.

Usage:
  uv run --env-file .env python scripts/grade_base_gemini.py \
      --root runs/harbor_base_matrix/antigravity-cli \
      --out runs/base_gemini_scores_agy.json
"""
from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
# Reuse Phylo's exact judge machinery (prompt, rubric parsing, level->points).
from regrade_gemini import (  # noqa: E402
    MODEL, _client, build_prompt, extract_json, parse_rubric_levels, score_from_levels,
)

RUBRIC_ROOT = ROOT / "data/biomnibench-da"


def rubric_max(rubric: str) -> float:
    """Max attainable Phylo score = sum of the best level's points per criterion."""
    levels = parse_rubric_levels(rubric)
    return sum(max(pts.values()) for pts in levels.values() if pts) or 0.0


def latest_trace_answer(task_dir: Path) -> tuple[str, str] | None:
    """(trace, answer) from the most recent run's artifacts; trace may be empty."""
    runs = sorted([d for d in task_dir.iterdir() if d.is_dir()])
    for run in reversed(runs):
        ans = sorted(run.rglob("artifacts/answer.txt"))
        tr = sorted(run.rglob("artifacts/trace.md"))
        if ans:
            return (tr[0].read_text(errors="replace") if tr else "",
                    ans[0].read_text(errors="replace"))
    return None


def grade_one(task_dir: Path) -> dict:
    task = task_dir.name
    rubric_f = RUBRIC_ROOT / task / "tests" / "rubric.txt"
    if not rubric_f.exists():
        return {"task": task, "gemini_score": None, "note": "no rubric"}
    ta = latest_trace_answer(task_dir)
    if ta is None:
        return {"task": task, "gemini_score": None, "note": "no answer.txt"}
    trace, answer = ta
    rubric = rubric_f.read_text()
    try:
        r = _client.models.generate_content(model=MODEL, contents=build_prompt(rubric, trace, answer))
        # Gemini wraps as {"criteria": {criterion_N: {level, reason}}, "overall_reasoning": ...};
        # score_from_levels wants that inner dict (matches regrade_gemini.judge()).
        criteria = extract_json(r.text).get("criteria", {})
        score = score_from_levels(rubric, criteria)
        mx = rubric_max(rubric)
        return {"task": task, "gemini_score": score, "max": mx,
                "normalized": round(score / mx, 3) if mx else None, "n_criteria": len(criteria)}
    except Exception as e:  # noqa: BLE001 — record per-task failure, keep going
        return {"task": task, "gemini_score": None, "note": f"error: {e}"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True, help="runs/harbor_base_matrix/<agent>")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--width", type=int, default=8, help="parallel judge calls")
    args = ap.parse_args()

    tasks = sorted(d for d in args.root.iterdir() if d.is_dir())
    print(f"grading {len(tasks)} base tasks with {MODEL} ({args.width}-wide)...", flush=True)
    with ThreadPoolExecutor(max_workers=args.width) as ex:
        results = list(ex.map(grade_one, tasks))
    for r in results:
        print(f"  {r['task']:14} score={r.get('gemini_score')} "
              f"norm={r.get('normalized')} {r.get('note','')}")
    args.out.write_text(json.dumps(results, indent=2))
    scored = [r for r in results if r.get("gemini_score") is not None]
    norms = [r["normalized"] for r in scored if r.get("normalized") is not None]
    print(f"\ngraded {len(scored)}/{len(results)} -> {args.out}")
    if norms:
        print(f"mean normalized capability = {sum(norms)/len(norms):.3f} "
              f"(min {min(norms):.2f}, max {max(norms):.2f})")


if __name__ == "__main__":
    main()
