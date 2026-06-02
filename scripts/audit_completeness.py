#!/usr/bin/env python3
"""Audit local BiomniBench-DA task data against the HF manifest.

complete() in download_robust only checks that environment/data is NON-EMPTY — it
cannot tell a partial pull (1 of 3 files) from a full one. An incomplete task
silently produces INVALID variants: the perturbation may target a secondary file
while the rubric's primary answer file is simply absent. This compares each task's
local files to the exact set HF ships at the pinned revision and reports any gaps.

Usage:
  uv run --env-file .env python scripts/audit_completeness.py
  uv run --env-file .env python scripts/audit_completeness.py --write-need /tmp/refetch.txt
"""
from __future__ import annotations
import argparse, os, sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SPECS = ROOT / "benchmarks/specs/biomnibench-da"
DATA = ROOT / "data/biomnibench-da"
REPO = "phylobio/BiomniBench-DA"
PINNED = "810b6c54a81e98019bb6c36bdbdc1d4e93dd46d1"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write-need", type=Path, help="write incomplete task ids here (one per line) for re-download")
    ap.add_argument("--tasks", nargs="*", help="limit to these task ids (default: every task that has a spec)")
    args = ap.parse_args()

    from huggingface_hub import HfApi
    files = HfApi(token=os.environ.get("HF_TOKEN")).list_repo_files(REPO, repo_type="dataset", revision=PINNED)

    tasks = args.tasks or sorted({yaml.safe_load(p.read_text())["base_task"] for p in SPECS.glob("*.yaml")})
    incomplete = []
    for t in tasks:
        key = f"{t}/environment/data/"               # HF paths carry no leading slash
        hf = {f.split("/environment/data/", 1)[-1] for f in files if f.startswith(key)}
        locd = DATA / t / "environment" / "data"
        loc = {str(p.relative_to(locd)) for p in locd.rglob("*") if p.is_file()} if locd.is_dir() else set()
        missing = hf - loc
        if missing:
            incomplete.append((t, len(hf), len(loc), sorted(missing)))

    print(f"audited {len(tasks)} tasks | INCOMPLETE: {len(incomplete)}")
    for t, nh, nl, miss in incomplete:
        print(f"  {t}: HF={nh} local={nl}  missing={miss}")
    if args.write_need and incomplete:
        args.write_need.write_text("\n".join(t for t, *_ in incomplete) + "\n")
        print(f"wrote {len(incomplete)} task ids -> {args.write_need}")
    sys.exit(1 if incomplete else 0)


if __name__ == "__main__":
    main()
