#!/usr/bin/env python3
"""Rebuild ONE adversarial variant's full data on demand from its committed spec.

For heavy variants (e.g. 11GB h5ad) we store only the spec + gate proof, not the
data (see generate_variants.py --skip-heavy-mb). This regenerates the full,
gate-validated variant data just-in-time so an agent run can use it; delete it
again afterward. Deterministic: same spec + pinned base data -> identical bytes.

Usage:
  uv run --env-file .env python scripts/materialize_variant.py da-17-1_drop_disease
  uv run python scripts/materialize_variant.py da-17-1_drop_disease --out /tmp/run_xyz
"""
from __future__ import annotations
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from benchmarks.variant_pipeline.spec import VariantSpec       # noqa: E402
from benchmarks.variant_pipeline.builder import build_variant  # noqa: E402
import yaml  # noqa: E402

SPECS = ROOT / "benchmarks/specs/biomnibench-da"
BASE = ROOT / "data/biomnibench-da"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("variant", help="variant name, e.g. da-17-1_drop_disease")
    ap.add_argument("--out", type=Path, default=ROOT / "runs/variants",
                    help="output root (default runs/variants)")
    ap.add_argument("--base", type=Path, default=BASE)
    args = ap.parse_args()

    sp = SPECS / f"{args.variant}.yaml"
    if not sp.exists():
        sys.exit(f"no spec: {sp}")
    spec = VariantSpec.from_dict(yaml.safe_load(sp.read_text()))
    out_dir = args.out / spec.name / "environment" / "data"
    base_task_dir = args.base / spec.base_task / "environment" / "data"

    r = build_variant(spec, base_task_dir, out_dir)
    if not r.emitted:
        sys.exit(f"FAILED to materialize {args.variant}: {r.error}")
    print(f"materialized {args.variant} -> {out_dir}")
    print(f"  gate: {len(r.checks)} checks all passed (variant is provably unanswerable)")


if __name__ == "__main__":
    main()
