#!/usr/bin/env python3
"""Assemble a self-contained review bundle for all adversarial-variant specs.

For each spec: the question (from base instruction.md), what the variant does
(ops, in plain terms), the gate proof (validator checks + pass/fail), the
expected behavior, and the author's notes (why unanswerable + hazards covered).
Emits runs/review/variants_review.json — consumed by the static review page.

Run: uv run python scripts/build_review_bundle.py
"""
import glob, json, os, re
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[1]
SPECS = ROOT / "benchmarks/specs/biomnibench-da"
DATA = ROOT / "data/biomnibench-da"
MANIFEST = ROOT / "runs/variants/MANIFEST.json"
OUT = ROOT / "runs/review/variants_review.json"

MODE = {  # infer defect mode from spec ops/name
    "single_group": "single-group collapse", "single_cell_type": "single-group collapse",
    "tiny_n": "statistical underpowering", "tiny_universe": "statistical underpowering",
}


def question_of(base_task: str) -> str:
    f = DATA / base_task / "instruction.md"
    if not f.exists():
        return "(instruction.md not found locally)"
    txt = f.read_text(errors="replace")
    m = re.search(r"##\s*Question\s*\n(.+?)(?:\n##|\Z)", txt, re.S)
    return (m.group(1).strip()[:700] if m else txt[:500])


def mode_of(spec: dict) -> str:
    name = spec["name"]
    for k, v in MODE.items():
        if k in name:
            return v
    kinds = {o["kind"] for o in spec.get("ops", [])}
    if "reduce_n" in kinds:
        return "statistical underpowering"
    if "subset_to_single_group" in kinds:
        return "single-group collapse"
    return "drop-column (structural)"


def main():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {"variants": {}}
    mvar = manifest.get("variants", {})

    rows = []
    for sp in sorted(SPECS.glob("*.yaml")):
        spec = yaml.safe_load(sp.read_text())
        name = spec["name"]
        m = mvar.get(name, {})
        rows.append({
            "name": name,
            "base_task": spec["base_task"],
            "mode": mode_of(spec),
            "expected_behavior": spec.get("expected_behavior", "refuse"),
            "question": question_of(spec["base_task"]),
            "ops": [{"kind": o["kind"], **{k: v for k, v in o.items() if k != "kind"}} for o in spec.get("ops", [])],
            "checks": [{"kind": c["kind"], **{k: v for k, v in c.items() if k != "kind"}} for c in spec.get("required_signal", [])],
            "notes": spec.get("notes", "").strip(),
            "emitted": m.get("emitted"),
            "gate_error": m.get("error", ""),
            "gate_checks": m.get("checks", []),
            "checksum": m.get("checksum"),
            "spec_path": str(sp.relative_to(ROOT)),
        })

    by_task = {}
    for r in rows:
        by_task.setdefault(r["base_task"], []).append(r["name"])
    summary = {
        "total_specs": len(rows),
        "emitted": sum(1 for r in rows if r["emitted"]),
        "rejected": sum(1 for r in rows if r["emitted"] is False),
        "base_tasks": len(by_task),
        "by_mode": {},
        "dataset_revision": manifest.get("pinned_revision"),
    }
    for r in rows:
        if r["emitted"]:
            summary["by_mode"][r["mode"]] = summary["by_mode"].get(r["mode"], 0) + 1
    OUT.write_text(json.dumps({"summary": summary, "variants": rows}, indent=2))
    print(f"wrote {OUT}")
    print(f"  {summary['emitted']} emitted / {summary['total_specs']} specs over {summary['base_tasks']} tasks")
    print(f"  by mode: {summary['by_mode']}")


if __name__ == "__main__":
    main()
