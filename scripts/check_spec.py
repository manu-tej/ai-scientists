#!/usr/bin/env python3
"""Build & gate ONE variant spec in isolation, print the result, delete the bytes.

For authoring/iterating on a single spec without touching the shared
runs/variants dir or duplicating large data (builds to a temp dir, removes it
after — same disk discipline as generate_variants --skip-heavy-mb). Exit 0 iff
the variant EMITS (every required_signal check passed = provably unanswerable).

Usage:
  uv run python scripts/check_spec.py benchmarks/specs/biomnibench-da/da-3-5_drop_x.yaml
"""
from __future__ import annotations
import sys, tempfile, shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from benchmarks.variant_pipeline.spec import VariantSpec        # noqa: E402
from benchmarks.variant_pipeline.builder import build_variant   # noqa: E402
import yaml                                                      # noqa: E402

BASE = ROOT / "data/biomnibench-da"


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit("usage: check_spec.py <spec.yaml>")
    sp = Path(sys.argv[1])
    spec = VariantSpec.from_dict(yaml.safe_load(sp.read_text()))
    base_task_dir = BASE / spec.base_task / "environment" / "data"
    if not base_task_dir.exists():
        sys.exit(f"NO DATA for base task {spec.base_task}: {base_task_dir}")
    tmp = Path(tempfile.mkdtemp(prefix=f"checkspec_{spec.name}_"))
    try:
        r = build_variant(spec, base_task_dir, tmp / "environment" / "data")
        for c in (r.checks or []):
            print(f"  {'✓' if c.passed else '✗'} {c.kind}: {c.detail}")
        if r.emitted:
            print(f"EMIT ✓ {spec.name} ({len(r.checks)} gate checks passed — provably unanswerable)")
            sys.exit(0)
        print(f"REJECT ✗ {spec.name}: {r.error}")
        sys.exit(1)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)  # never leave build bytes on disk


if __name__ == "__main__":
    main()
