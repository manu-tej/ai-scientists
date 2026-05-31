"""Build + validate adversarial variants from YAML specs, then write a manifest.

For each spec under benchmarks/specs/<benchmark>/:
  - build_mode=rebuild           -> construct the variant from base data (gated on validation)
  - build_mode=validate_existing -> validate the EXISTING variant data in place
The variant data lives at data/biomnibench-da/<name>/environment/data; the variant
dir's instruction.md / task.toml / tests are left untouched.

Usage:
    uv run scripts/build_variants.py                 # all specs
    uv run scripts/build_variants.py --only da-5-1_drop_tier
    uv run scripts/build_variants.py --exclude da-17-1_drop_disease
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rich.console import Console

from benchmarks.variant_pipeline import VariantSpec, build_variant
from benchmarks.variant_pipeline.builder import BuildResult
from benchmarks.variant_pipeline.validator import validate
from benchmarks.variant_pipeline.manifest import write_manifest

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "data/biomnibench-da"
SPECS = ROOT / "benchmarks/specs/biomnibench-da"
MANIFEST = ROOT / "benchmarks/manifest.json"


def base_data(task: str) -> Path:
    return DATASET / task / "environment" / "data"


def process(spec: VariantSpec, console: Console) -> BuildResult:
    out = base_data(spec.name)
    if spec.build_mode == "validate_existing":
        if not out.exists():
            return BuildResult(spec.name, emitted=False, error="validate_existing: variant data missing")
        checks = validate(spec, out)
        ok = all(c.passed for c in checks)
        return BuildResult(spec.name, emitted=ok, checks=checks,
                           error="" if ok else "validation_failed (existing data)")
    return build_variant(spec, base_data(spec.base_task), out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only")
    ap.add_argument("--exclude", action="append", default=[])
    args = ap.parse_args()
    console = Console()

    specs = [VariantSpec.from_yaml(p) for p in sorted(SPECS.glob("*.yaml"))]
    if args.only:
        specs = [s for s in specs if s.name == args.only]
    specs = [s for s in specs if s.name not in set(args.exclude)]

    results = []
    for spec in specs:
        console.print(f"[cyan]{spec.name}[/] ({spec.build_mode})")
        res = process(spec, console)
        results.append(res)
        tag = "[green]EMITTED+VALID[/]" if res.all_passed else ("[green]VALIDATED[/]" if res.emitted else "[red]FAILED[/]")
        console.print(f"   {tag} {res.error}")
        for c in res.checks:
            mark = "[green]✓[/]" if c.passed else "[red]✗[/]"
            console.print(f"     {mark} {c.kind}: {c.detail}")

    # Merge into any existing manifest so partial runs accumulate.
    if MANIFEST.exists() and (args.only or args.exclude):
        import json
        prior = {r["name"]: r for r in json.loads(MANIFEST.read_text()).get("variants", [])}
        for res in results:
            prior.pop(res.name, None)
        # rebuild BuildResult-likes for prior rows we keep
        keep = list(prior.values())
        out = write_manifest(results, MANIFEST)
        merged = {r["name"]: r for r in out["variants"]}
        for row in keep:
            merged.setdefault(row["name"], row)
        rows = list(merged.values())
        summary = {"total": len(rows),
                   "emitted": sum(1 for r in rows if r["emitted"]),
                   "validated": sum(1 for r in rows if r["validated"]),
                   "failed": [r["name"] for r in rows if not r["emitted"]]}
        MANIFEST.write_text(__import__("json").dumps({"summary": summary, "variants": rows}, indent=2))
        console.print(f"\n[bold]manifest (merged):[/] {summary['validated']}/{summary['total']} validated")
    else:
        out = write_manifest(results, MANIFEST)
        s = out["summary"]
        console.print(f"\n[bold]manifest:[/] {s['validated']}/{s['total']} validated; failed={s['failed']}")


if __name__ == "__main__":
    main()
