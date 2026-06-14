#!/usr/bin/env python3
"""Patch re-graded scores into per-agent grade files, with backups + provenance.

Generalises the one-off correction done for BiomniBench-DA (2026-06-13) so the same
"fix a defect -> re-grade -> patch the score of record" loop is reproducible for any
dataset that stores grades as one JSON-list-of-cells per agent.

WHAT IT DOES
------------
For each requested patch (agent, task), it copies the *grading* fields
(median/mean/sd/min/max/norms/n_reps/reps) from a freshly-graded source JSON into the
official grade file's matching cell, stamps a ``_corrected`` provenance block, and leaves
everything else untouched. Every grade file is backed up before the first write.

It does NOT call any judge — run the re-grade first (see scripts/regrade_serene.sh), then
point this at the resulting JSONs.

MANIFEST (JSON)
---------------
{
  "grades_dir": "results/biomnibench/grades",
  "file_template": "biomni_{agent}_minimax.json",   // {agent} -> agent key below
  "judge": "minimax/minimax-m3",
  "backup_suffix": ".bak-precorrection",
  "grade_fields": ["n_reps","norms","median","mean","sd","min","max","reps"],  // optional override
  "patches": [
    {"agent":"cc","task":"da-26-2","source":"runs/clean_regrade_smoke_claude-code.json",
     "reason":"re-run under fixed instruction (method disclosed)"},
    {"agent":"agy","task":"da-15-8","source":"runs/cap3_regrade_agy.json",
     "reason":"re-graded vs fixed rubric"}
  ]
}

Each ``source`` is a JSON list of graded cells ``[{"task":..., "median":..., "norms":[...], ...}]``
(the output format of bench/grade.py and scripts/grade_reps.py). The cell whose ``task`` matches
is used.

USAGE
-----
  python scripts/patch_grades.py --manifest patch.json
  python scripts/patch_grades.py --manifest patch.json --dry-run    # show diffs, write nothing
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import shutil
import sys
from pathlib import Path

DEFAULT_GRADE_FIELDS = ["n_reps", "norms", "median", "mean", "sd", "min", "max", "reps"]


def _find(cells: list[dict], task: str) -> dict | None:
    return next((c for c in cells if c.get("task") == task), None)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--manifest", required=True, type=Path, help="patch manifest JSON (see module docstring)")
    ap.add_argument("--date", default=None, help="provenance date (default: today, system time)")
    ap.add_argument("--dry-run", action="store_true", help="print the before/after table, write nothing")
    args = ap.parse_args()

    m = json.loads(args.manifest.read_text())
    grades_dir = Path(m["grades_dir"])
    file_template = m["file_template"]
    judge = m.get("judge", "unknown")
    backup_suffix = m.get("backup_suffix", ".bak-precorrection")
    grade_fields = m.get("grade_fields", DEFAULT_GRADE_FIELDS)
    date = args.date or _dt.date.today().isoformat()

    # Cache source files + loaded grade files; back up each grade file once.
    sources: dict[str, list] = {}
    grade_cache: dict[Path, list] = {}
    backed_up: set[Path] = set()
    rows = []

    for p in m["patches"]:
        agent, task = p["agent"], p["task"]
        gf = grades_dir / file_template.format(agent=agent)
        if not gf.exists():
            print(f"  ERROR grade file missing: {gf}", file=sys.stderr)
            return 2
        if gf not in grade_cache:
            grade_cache[gf] = json.loads(gf.read_text())
        cells = grade_cache[gf]

        src_path = p["source"]
        if src_path not in sources:
            sources[src_path] = json.loads(Path(src_path).read_text())
        new = _find(sources[src_path], task)
        old = _find(cells, task)
        if new is None or old is None:
            print(f"  WARN no {'source' if new is None else 'target'} entry for {agent}/{task}; skip", file=sys.stderr)
            continue

        prior_median = old.get("median")
        if not args.dry_run:
            # Back up before the first modification of this file.
            if gf not in backed_up:
                shutil.copyfile(gf, gf.with_name(gf.name + backup_suffix))
                backed_up.add(gf)
            for f in grade_fields:
                if f in new:
                    old[f] = new[f]
            old["_corrected"] = {"date": date, "reason": p.get("reason", ""),
                                 "prior_median": prior_median, "judge": judge}
        rows.append((agent, task, prior_median, new.get("median"), new.get("n_reps")))

    # Write back (one write per file).
    if not args.dry_run:
        for gf, cells in grade_cache.items():
            if gf in backed_up:
                gf.write_text(json.dumps(cells, indent=1))

    label = "DRY-RUN (no writes)" if args.dry_run else f"patched {len(rows)} cells in {len(backed_up)} file(s)"
    print(f"{'agent':6} {'task':14} {'OLD':>7} {'NEW':>7} {'n_reps':>6}")
    for a, t, o, n, nr in sorted(rows):
        print(f"{a:6} {t:14} {str(o):>7} {str(n):>7} {str(nr):>6}")
    print(f"\n{label}  (backups: *{backup_suffix})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
