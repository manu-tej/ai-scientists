"""Build an isolated affordance-carrying base-task tree from an EXISTING migrated tree.

For the codex false-refusal control: clone runs/harbor_base_tasks -> runs/harbor_base_aff,
hardlinking the heavy data (≈0 disk), copying the already-migrated scaffolding as-is (no
re-migration), and appending the byte-identical refuse/escalate affordance to each
instruction. Leaves the source tree (an in-flight arm may be reading it) untouched.

Usage: uv run python scripts/build_base_aff.py [--src runs/harbor_base_tasks] [--out runs/harbor_base_aff]
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from harbor_migrate import REFUSAL_AFFORDANCE, _link_tree  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", type=Path, default=ROOT / "runs/harbor_base_tasks")
    ap.add_argument("--out", type=Path, default=ROOT / "runs/harbor_base_aff")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    def skip_data(dirpath, names):
        return ["data"] if Path(dirpath).name == "environment" else []

    n = 0
    for t in sorted(args.src.iterdir()):
        if not (t / "task.toml").exists():
            continue
        dst = args.out / t.name
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(t, dst, ignore=skip_data)              # scaffolding (own inodes)
        _link_tree(t / "environment" / "data", dst / "environment" / "data")  # hardlink data
        instr = dst / "instruction.md"
        if instr.exists():
            txt = instr.read_text()
            if "INSUFFICIENT DATA" not in txt:
                instr.write_text(txt + "\n\n" + REFUSAL_AFFORDANCE)
        n += 1
        print(f"  built {t.name}")
    print(f"built {n} affordance base tasks -> {args.out}")


if __name__ == "__main__":
    main()
