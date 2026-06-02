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
SOURCES = ROOT / "benchmarks/sources.json"   # DA-group -> source publication (PubMed-resolved)
OUT = ROOT / "runs/review/variants_review.json"


def source_of(base_task: str) -> dict:
    """Source publication for a task's DA group (raw provenance, no scores)."""
    if not SOURCES.exists():
        return {}
    m = re.match(r"da-(\d+)-", base_task)
    return json.loads(SOURCES.read_text()).get(m.group(1), {}) if m else {}

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
    return (m.group(1).strip() if m else txt[:800])


def title_of(base_task: str) -> str:
    """Human title from instruction.md's '# Task: ...' line."""
    f = DATA / base_task / "instruction.md"
    if not f.exists():
        return base_task
    for line in f.read_text(errors="replace").splitlines():
        m = re.match(r"#\s*Task:\s*(.+)", line)
        if m:
            return m.group(1).strip()
    return base_task


def rubric_of(base_task: str) -> str:
    """Full grading rubric (tests/rubric.txt) so the reviewer can see exactly what
    the original task is scored on — the variant must remove that scorable signal."""
    f = DATA / base_task / "tests" / "rubric.txt"
    return f.read_text(errors="replace").strip() if f.exists() else "(rubric.txt not found locally)"


def _tasknum(t: str):
    """Natural sort key for da-<a>-<b>."""
    parts = re.findall(r"\d+", t)
    return tuple(int(p) for p in parts) if parts else (0,)


def op_summary(o: dict) -> str:
    """Plain-English summary of one perturbation op, naming the EXACT columns/files
    removed — so a reviewer (and a flag reason) can reference precisely what was dropped."""
    k = o.get("kind"); f = o.get("file", ""); sh = o.get("sheet"); hr = o.get("header_row")
    loc = f + (f" [sheet {sh}]" if sh else "") + (f" [header_row {hr}]" if hr not in (None, 0) else "")
    if k == "drop_columns":
        return f"dropped column(s) {o.get('columns')} from {loc}"
    if k == "drop_columns_matching":
        return f"dropped columns matching /{o.get('pattern')}/ from {loc}"
    if k == "subset_to_single_group":
        return f"collapsed {loc} to a single group: {o.get('column')} == {o.get('keep_value')!r} (other groups removed)"
    if k == "drop_rows_by_value":
        return f"kept only rows where {o.get('column')} in {o.get('keep_values')} in {loc}"
    if k == "anonymize_column":
        return f"anonymized labels in column {o.get('column')!r} of {loc}"
    if k == "reduce_n":
        return f"subsampled {loc} to n={o.get('n')} rows (seed {o.get('seed', 0)})"
    if k == "drop_files_matching":
        return f"deleted all files matching '{o.get('glob')}'"
    if k == "anonymize_filenames":
        return f"renamed files matching '{o.get('glob')}' to neutral ids (group token stripped)"
    if k == "drop_lines_matching":
        return f"deleted lines matching /{o.get('pattern')}/ from {f}"
    return f"{k}: {o}"


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
            "ops": [{"kind": o["kind"], **{k: v for k, v in o.items() if k != "kind"}} for o in spec.get("ops", [])],
            "dropped": [op_summary({"kind": o["kind"], **{k: v for k, v in o.items() if k != "kind"}}) for o in spec.get("ops", [])],
            "checks": [{"kind": c["kind"], **{k: v for k, v in c.items() if k != "kind"}} for c in spec.get("required_signal", [])],
            "notes": spec.get("notes", "").strip(),
            "emitted": m.get("emitted"),
            "gate_error": m.get("error", ""),
            "gate_checks": m.get("checks", []),
            "checksum": m.get("checksum"),
            "spec_path": str(sp.relative_to(ROOT)),
        })

    # Group variants under their base task, with that task's question + rubric, so
    # the reviewer reads the original task once then assesses all its variants.
    by_task: dict[str, list] = {}
    for r in rows:
        by_task.setdefault(r["base_task"], []).append(r)
    tasks = []
    for t in sorted(by_task, key=_tasknum):
        vs = sorted(by_task[t], key=lambda r: r["name"])
        tasks.append({
            "base_task": t,
            "title": title_of(t),
            "source": source_of(t),
            "question": question_of(t),
            "rubric": rubric_of(t),
            "n_variants": len(vs),
            "n_emitted": sum(1 for v in vs if v["emitted"]),
            "n_rejected": sum(1 for v in vs if v["emitted"] is False),
            "modes": sorted({v["mode"] for v in vs}),
            "variants": vs,
        })

    summary = {
        "total_specs": len(rows),
        "emitted": sum(1 for r in rows if r["emitted"]),
        "rejected": sum(1 for r in rows if r["emitted"] is False),
        # in a spec file but absent from MANIFEST.json => not (re)generated yet,
        # NOT a gate failure. Distinguished so a stale manifest doesn't look broken.
        "ungenerated": sum(1 for r in rows if r["emitted"] is None),
        "base_tasks": len(by_task),
        "by_mode": {},
        "dataset_revision": manifest.get("pinned_revision"),
    }
    for r in rows:
        if r["emitted"]:
            summary["by_mode"][r["mode"]] = summary["by_mode"].get(r["mode"], 0) + 1
    OUT.write_text(json.dumps({"summary": summary, "tasks": tasks}, indent=2))
    print(f"wrote {OUT}")
    print(f"  {summary['emitted']} emitted / {summary['total_specs']} specs over {summary['base_tasks']} tasks")
    print(f"  by mode: {summary['by_mode']}")


if __name__ == "__main__":
    main()
