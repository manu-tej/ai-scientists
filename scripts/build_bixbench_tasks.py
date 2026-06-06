#!/usr/bin/env python3
"""Adapt BixBench-Verified-50 capsules into Harbor tasks (same contract as BiomniBench-DA).

Each JSONL record -> a Harbor task dir:
  <question_id>/{task.toml, instruction.md, environment/{Dockerfile, data/}, tests/grading.json}

CRITICAL: only CapsuleData/* goes into environment/data/. The executed CapsuleNotebook
(the worked solution, with the answer in it) is STRIPPED so the agent can't read the answer.

Grading is post-hoc (run.sh uses --disable-verification): tests/grading.json carries
{question, ideal, distractors, eval_mode, answer, hypothesis} for scripts/grade_bixbench.py.

Usage:
  python scripts/build_bixbench_tasks.py \
      --jsonl BixBench-Verified-50.jsonl \
      --capsules-dir <dir-with-CapsuleFolder-*.zip> \
      --out runs/bixbench_smoke \
      --ids bix-18-q3 bix-30-q3 bix-53-q2     # omit --ids to build all 50
"""
from __future__ import annotations
import argparse, json, shutil, tempfile, zipfile
from pathlib import Path

DOCKERFILE = """FROM ubuntu:24.04

RUN apt-get update && apt-get install -y \\
    python3 python3-pip python3-venv r-base r-base-dev curl wget git unzip \\
    && rm -rf /var/lib/apt/lists/*

# Raw capsule data ONLY (the executed reference notebook is intentionally excluded).
COPY data/ /app/data/
WORKDIR /app
"""

TASK_TOML = """schema_version = "1.3"
artifacts = [
    {{ source = "/app/answer.txt", destination = "answer.txt" }},
    {{ source = "/app/trace.md", destination = "trace.md" }},
]

[task]
name = "bixbench-v50/{tid}"
description = "BixBench-Verified-50 task (computational biology; capability + consistency)."
authors = [{{ name = "FutureHouse/Phylo (BixBench)" }}]
keywords = ["bioinformatics", "computational-biology", "bixbench"]

[metadata]
author_name = "BixBench-Verified-50"
difficulty = "unknown"
category = "bioinformatics"
task_type = "data-analysis"

[verifier]
timeout_sec = 900.0

[agent]
timeout_sec = 3600.0

[environment]
network_mode = "public"
build_timeout_sec = 600.0
os = "linux"
mcp_servers = []

[environment.env]
"""

INSTRUCTION = """<!-- TASK_ID: {tid} -->

# Task: {short_id}

## Question

{question}

## Data Files

The following files are provided in `/app/data/`:
{datafiles}

## Required Outputs

You MUST create the following two files:

### 1. Final Answer (`/app/answer.txt`)
Write your final answer to the question above in plain text. Be concise and specific: report the
exact value, category, or range the question asks for (a number, a short phrase, or a ratio).

### 2. Analysis Trace (`/app/trace.md`)
Document your analysis in markdown: objective; data inspected (files, shapes, key columns);
approach (the actual Python/R code you ran for each non-trivial step); quantitative intermediate
results; the final result; and what the analysis cannot conclude (limitations).

## Environment
- Python 3 and R are pre-installed; install any additional packages you need (internet available).
- Solve the task directly from the provided data and your domain knowledge.
- Do NOT search for or read the source paper, any notebook, or supplementary materials.
"""

# Harbor's task LOADER requires tests/test.sh to exist when [environment].os = "linux"
# (validated even under --disable-verification). BixBench is graded post-hoc by
# scripts/grade_bixbench.py, so this is a no-op verifier that just preserves outputs.
TEST_SH = """#!/bin/bash
# BixBench-Verified-50: graded post-hoc by scripts/grade_bixbench.py (run.sh uses
# --disable-verification). This exists to satisfy Harbor's loader; it preserves outputs.
cp /app/answer.txt /logs/verifier/answer.txt 2>/dev/null || echo "Warning: answer.txt not found"
cp /app/trace.md /logs/verifier/trace.md 2>/dev/null || echo "Warning: trace.md not found"
exit 0
"""


def build_task(rec: dict, capsules_dir: Path, out_root: Path) -> tuple[str | None, str]:
    tid = rec["question_id"]                      # e.g. bix-18-q3
    cap_zip = capsules_dir / rec["data_folder"]
    if not cap_zip.exists():
        return None, f"missing capsule {cap_zip.name}"

    out = out_root / tid
    if out.exists():
        shutil.rmtree(out)
    data_dir = out / "environment" / "data"
    data_dir.mkdir(parents=True)

    # unzip capsule; copy ONLY CapsuleData/* (strip the executed notebook)
    copied: list[str] = []
    with tempfile.TemporaryDirectory() as td:
        with zipfile.ZipFile(cap_zip) as z:
            z.extractall(td)
        data_src = next((p for p in Path(td).iterdir()
                         if p.is_dir() and p.name.startswith("CapsuleData")), None)
        if data_src is None:
            shutil.rmtree(out)
            return None, "no CapsuleData/ in capsule"
        for f in sorted(data_src.rglob("*")):
            if f.is_file():
                rel = f.relative_to(data_src)
                dst = data_dir / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(f, dst)
                copied.append(str(rel))

    (out / "environment" / "Dockerfile").write_text(DOCKERFILE)
    (out / "task.toml").write_text(TASK_TOML.format(tid=tid))
    datafiles = "\n".join(f"- `{c}`" for c in copied) or "- (see `/app/data/`)"
    (out / "instruction.md").write_text(INSTRUCTION.format(
        tid=tid, short_id=rec.get("short_id", tid),
        question=rec["question"], datafiles=datafiles))

    tdir = out / "tests"
    tdir.mkdir()
    (tdir / "grading.json").write_text(json.dumps({
        "question_id": tid,
        "question": rec["question"],
        "ideal": rec["ideal"],
        "distractors": rec.get("distractors", []),
        "eval_mode": rec.get("eval_mode"),
        "answer": rec.get("answer"),
        "hypothesis": rec.get("hypothesis"),
        "capsule_uuid": rec.get("capsule_uuid"),
        "categories": rec.get("categories"),
    }, indent=2))
    test_sh = tdir / "test.sh"
    test_sh.write_text(TEST_SH)
    test_sh.chmod(0o755)
    return tid, f"{len(copied)} data file(s), eval={rec.get('eval_mode')}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--jsonl", required=True, type=Path)
    ap.add_argument("--capsules-dir", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--ids", nargs="*", help="subset of question_ids (smoke test); omit = all")
    args = ap.parse_args()

    recs = [json.loads(l) for l in args.jsonl.read_text().splitlines() if l.strip()]
    if args.ids:
        want = set(args.ids)
        recs = [r for r in recs if r["question_id"] in want]
        missing = want - {r["question_id"] for r in recs}
        for m in sorted(missing):
            print(f"  WARN requested id not in jsonl: {m}")
    args.out.mkdir(parents=True, exist_ok=True)

    ok = 0
    for r in recs:
        tid, msg = build_task(r, args.capsules_dir, args.out)
        print(f"  {'OK  ' if tid else 'SKIP'} {r['question_id']}: {msg}")
        ok += bool(tid)
    print(f"\nbuilt {ok}/{len(recs)} tasks -> {args.out}")


if __name__ == "__main__":
    main()
