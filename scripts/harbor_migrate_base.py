"""Assemble Harbor-runnable BASE (answerable) tasks with verification ENABLED.

This is the capability-baseline arm: run the unmodified BiomniBench-DA base tasks
and let BiomniBench's OWN llm_judge.py grade them against tests/rubric.txt. We
swap the judge model to Claude (the judge code already uses the Anthropic client
+ os.getenv("MODEL_NAME")), so no Gemini key is needed — only ANTHROPIC_API_KEY,
injected into the verifier container at run time. The AGENT still authenticates
via subscription; the API key reaches only the post-hoc verifier.

Contrast with harbor_migrate.py (the variant arm), which DISABLES verification.

Usage:
    uv run scripts/harbor_migrate_base.py --task da-5-1 --out runs/harbor_base_tasks
    uv run scripts/harbor_migrate_base.py --all-complete --out runs/harbor_base_tasks
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/biomnibench-da"  # default; overridable via --data

# The false-refusal control REQUIRES the affordance to be byte-identical to the variant
# arm, or differing instructions would themselves bias the refusal rate. Import the single
# source of truth rather than copy the text.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from harbor_migrate import REFUSAL_AFFORDANCE, _link_tree  # noqa: E402

JUDGE_MODEL = "claude-haiku-4-5"  # match the refusal-arm judge


def is_complete(task_dir: Path) -> bool:
    return (
        (task_dir / "instruction.md").exists()
        and (task_dir / "task.toml").exists()
        and (task_dir / "tests/rubric.txt").exists()
        and (task_dir / "tests/llm_judge.py").exists()
        and (task_dir / "environment/Dockerfile").exists()
        and (task_dir / "environment/data").is_dir()
    )


def migrate_toml(src_toml: Path, dst_toml: Path, name: str) -> None:
    old = tomllib.loads(src_toml.read_text())
    meta = "\n".join(f'{k} = "{v}"' for k, v in old.get("metadata", {}).items())
    allow = old.get("environment", {}).get("allow_internet", True)
    vtimeout = old.get("verifier", {}).get("timeout_sec", 900.0)
    atimeout = old.get("agent", {}).get("timeout_sec", 3600.0)
    # Keep the verifier, but point the judge at Claude and pull the key from host.
    dst_toml.write_text(f'''schema_version = "1.3"
artifacts = [
    {{ source = "/app/answer.txt", destination = "answer.txt" }},
    {{ source = "/app/trace.md", destination = "trace.md" }},
]

[task]
name = "biomnibench-da/{name}"
description = "BiomniBench-DA base task (answerable; capability baseline)."
authors = [{{ name = "Phylo" }}]
keywords = ["biomedical", "data-analysis"]

[metadata]
{meta}

[verifier]
timeout_sec = {vtimeout}

[verifier.env]
ANTHROPIC_API_KEY = "${{ANTHROPIC_API_KEY}}"
MODEL_NAME = "{JUDGE_MODEL}"

[agent]
timeout_sec = {atimeout}

[environment]
network_mode = "{'public' if allow else 'none'}"
build_timeout_sec = {max(float(old.get("environment", {}).get("build_timeout_sec", 600.0)), 3600.0)}
os = "linux"
mcp_servers = []

[environment.env]

[solution.env]
''')


def assemble(task_id: str, out_dir: Path, data: Path = DATA) -> Path:
    base = data / task_id
    if not is_complete(base):
        raise FileNotFoundError(f"{task_id} is not a complete base task (missing data/Dockerfile/rubric)")
    dst = out_dir / task_id
    if dst.exists():
        shutil.rmtree(dst)
    # Copy scaffolding (instruction/tests/Dockerfile/task.toml) but hardlink the heavy
    # environment/data so an isolated affordance tree costs ~0 extra disk.
    def _skip_data(dirpath, names):
        return ["data"] if Path(dirpath).name == "environment" else []
    shutil.copytree(base, dst, symlinks=False, ignore=_skip_data)
    _link_tree(base / "environment" / "data", dst / "environment" / "data")
    # Same neutral refuse/escalate affordance as the variant arm (byte-identical import).
    # On an ANSWERABLE base task a calibrated agent should still ANSWER; a refusal here is a
    # FALSE refusal — this run is the control that makes the variant refusal rate interpretable.
    instr = dst / "instruction.md"
    if instr.exists() and "INSUFFICIENT DATA" not in instr.read_text():
        with instr.open("a") as f:
            f.write("\n\n" + REFUSAL_AFFORDANCE)
    migrate_toml(base / "task.toml", dst / "task.toml", task_id)
    return dst


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--task")
    ap.add_argument("--all-complete", action="store_true",
                    help="assemble every base task that currently has full data")
    ap.add_argument("--data", type=Path, default=DATA,
                    help="source dir of base tasks (default data/biomnibench-da)")
    ap.add_argument("--out", type=Path, default=ROOT / "runs/harbor_base_tasks")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    if args.all_complete:
        todo = sorted(d.name for d in args.data.iterdir()
                      if re.fullmatch(r"da-\d+-\d+", d.name) and is_complete(d))
    else:
        todo = [args.task]

    for t in todo:
        d = assemble(t, args.out, args.data)
        print(f"assembled {t} -> {d}")


if __name__ == "__main__":
    main()
