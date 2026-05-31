"""Assemble complete, Harbor-runnable tasks from BiomniBench tasks + our variants.

The adversarial variant dirs only carry perturbed `environment/data` (+ a stub
instruction/task.toml); they lack `tests/` and `environment/Dockerfile`, so
Harbor rejects them. This builds a faithful Harbor task by taking the BASE task
(instruction, tests, Dockerfile) and swapping in the variant's perturbed data,
then migrating task.toml from BiomniBench schema (version="1.0") to Harbor 1.3.

Usage:
    uv run scripts/harbor_migrate.py --task da-13-3_drop_pvalues --out /tmp/harbor_tasks
    uv run scripts/harbor_migrate.py --all-validated --out runs/harbor_tasks
"""
from __future__ import annotations

import argparse
import re
import shutil
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/biomnibench-da"

VALIDATED = [  # the 9 gate-validated variants (da-3-4 pair excluded: .xls S1A leak)
    "da-20-1_drop_cell_line", "da-20-1_single_cell_type", "da-5-1_drop_pdac",
    "da-12-4_tiny_n", "da-12-4_drop_survival", "da-5-1_drop_tier",
    "da-13-3_drop_pvalues", "da-13-3_drop_pct_fat", "da-17-1_drop_disease",
]


def base_of(task_id: str) -> str:
    m = re.match(r"(da-\d+-\d+)", task_id)
    if not m:
        raise ValueError(f"cannot derive base task from {task_id!r}")
    return m.group(1)


def migrate_toml(src_toml: Path, dst_toml: Path, name: str) -> None:
    old = tomllib.loads(src_toml.read_text())
    meta = "\n".join(f'{k} = "{v}"' for k, v in old.get("metadata", {}).items())
    venv = "\n".join(f'{k} = "{v}"' for k, v in old.get("verifier", {}).get("env", {}).items())
    allow = old.get("environment", {}).get("allow_internet", True)
    dst_toml.write_text(f'''schema_version = "1.3"
artifacts = []

[task]
name = "biomnibench-da/{name}"
description = "BiomniBench-DA task (gate-validated unanswerable variant)."
authors = [{{ name = "Phylo" }}]
keywords = ["biomedical", "data-analysis"]

[metadata]
{meta}

[verifier]
timeout_sec = {old.get("verifier", {}).get("timeout_sec", 900.0)}

[verifier.env]
{venv}

[agent]
timeout_sec = {old.get("agent", {}).get("timeout_sec", 3600.0)}

[environment]
network_mode = "{'public' if allow else 'none'}"
build_timeout_sec = {old.get("environment", {}).get("build_timeout_sec", 600.0)}
os = "linux"
mcp_servers = []

[environment.env]

[solution.env]
''')


def assemble(task_id: str, out_dir: Path) -> Path:
    """Build a complete Harbor task dir for task_id under out_dir."""
    is_variant = task_id not in {base_of(task_id)}
    base = DATA / base_of(task_id)
    dst = out_dir / task_id
    if dst.exists():
        shutil.rmtree(dst)
    # Start from the complete BASE task (instruction, tests, Dockerfile, data).
    shutil.copytree(base, dst, symlinks=False)
    # Swap in the variant's perturbed data (if this is a variant).
    if is_variant:
        var_data = DATA / task_id / "environment" / "data"
        if not var_data.exists():
            raise FileNotFoundError(f"variant data missing: {var_data}")
        shutil.rmtree(dst / "environment" / "data")
        shutil.copytree(var_data, dst / "environment" / "data", symlinks=False)
        # Use the variant's instruction if it has one (carries the perturbation framing).
        var_instr = DATA / task_id / "instruction.md"
        if var_instr.exists():
            shutil.copy2(var_instr, dst / "instruction.md")
    # Migrate task.toml schema.
    migrate_toml(base / "task.toml", dst / "task.toml", task_id)
    return dst


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--task")
    ap.add_argument("--all-validated", action="store_true")
    ap.add_argument("--out", type=Path, default=ROOT / "runs/harbor_tasks")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    todo = VALIDATED if args.all_validated else [args.task]
    for t in todo:
        d = assemble(t, args.out)
        print(f"assembled {t} -> {d}")


if __name__ == "__main__":
    main()
