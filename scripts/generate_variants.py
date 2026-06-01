#!/usr/bin/env python3
"""Deterministic adversarial-variant GENERATOR for BiomniBench-DA.

The reproducible artifact of this project: given (1) the pinned base dataset and
(2) the committed per-task specs in benchmarks/specs/, regenerate every validated
"unanswerable" variant from scratch — with NO LLM in the path. Each variant is
emitted ONLY if it passes the validator gate (the answer-critical signal is
provably gone, not re-encoded in a sibling column/sheet).

This is intentionally separate from running agents / judging refusals (those are
non-deterministic measurements that USE this output, documented in RUNBOOK).

Outputs:
  <out>/<variant_name>/...            the built+validated variant data
  <out>/MANIFEST.json                 provenance: dataset revision, per-spec
                                       gate results, checksums, tool versions

Usage:
  uv run --env-file .env python scripts/generate_variants.py --out runs/variants
  uv run python scripts/generate_variants.py --out runs/variants --no-verify-revision
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from benchmarks.variant_pipeline.spec import VariantSpec          # noqa: E402
from benchmarks.variant_pipeline.builder import build_variant     # noqa: E402

import yaml  # noqa: E402

SPECS_DIR = ROOT / "benchmarks/specs/biomnibench-da"
BASE_DATA = ROOT / "data/biomnibench-da"
DATASET_REPO = "phylobio/BiomniBench-DA"
# Pin: the dataset revision the specs were authored against. "The original 50
# tasks" means THIS sha — regeneration against a different sha is flagged.
PINNED_REVISION = "810b6c54a81e98019bb6c36bdbdc1d4e93dd46d1"


def _file_content_hash(f: Path) -> bytes:
    """Hash a file's LOGICAL content, robust to container metadata.

    Spreadsheets (.xls/.xlsx) embed a write timestamp in the zip, so raw bytes
    differ every rebuild even when the data is identical. Hash the cell values
    instead, so the checksum certifies "same data," not "same bytes." Other
    formats hash raw bytes.
    """
    if f.suffix.lower() in (".xlsx", ".xls"):
        try:
            import pandas as pd
            xl = pd.ExcelFile(f)
            parts = []
            for sheet in sorted(xl.sheet_names):
                df = xl.parse(sheet, header=None, dtype=str)
                parts.append(sheet.encode())
                parts.append(df.fillna("").to_csv(index=False).encode())
            return hashlib.sha256(b"".join(parts)).digest()
        except Exception:
            pass  # fall back to raw bytes
    return hashlib.sha256(f.read_bytes()).digest()


def _dir_checksum(d: Path) -> str:
    """Order-independent checksum of a variant dir's logical content."""
    h = hashlib.sha256()
    for f in sorted(p for p in d.rglob("*") if p.is_file()):
        h.update(f.relative_to(d).as_posix().encode())
        h.update(_file_content_hash(f))
    return h.hexdigest()[:16]


def _current_revision() -> str | None:
    try:
        from huggingface_hub import HfApi
        return HfApi(token=os.environ.get("HF_TOKEN")).dataset_info(DATASET_REPO).sha
    except Exception:
        return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=ROOT / "runs/variants")
    ap.add_argument("--base", type=Path, default=BASE_DATA)
    ap.add_argument("--specs", type=Path, default=SPECS_DIR)
    ap.add_argument("--no-verify-revision", action="store_true",
                    help="skip the HF dataset-revision provenance check")
    ap.add_argument("--skip-heavy-mb", type=int, default=0,
                    help="if >0: build+gate every variant, but for variants whose data "
                         "exceeds this many MB (e.g. 11GB h5ad), record the gate proof then "
                         "DELETE the built data — it is regenerated on demand via "
                         "materialize_variant.py. Keeps disk lean; gate proof preserved.")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    # --- provenance: confirm we're generating from the pinned base data ---
    rev = None if args.no_verify_revision else _current_revision()
    rev_ok = (rev == PINNED_REVISION) if rev else None
    if rev and not rev_ok:
        print(f"WARNING: live dataset revision {rev} != pinned {PINNED_REVISION}. "
              f"Variants may differ from the published set.", file=sys.stderr)

    specs = sorted(args.specs.glob("*.yaml"))
    print(f"generating {len(specs)} variants from {args.base} (pinned rev {PINNED_REVISION[:12]})")

    manifest = {
        "dataset_repo": DATASET_REPO,
        "pinned_revision": PINNED_REVISION,
        "live_revision": rev,
        "revision_match": rev_ok,
        "n_specs": len(specs),
        "variants": {},
        "summary": {"emitted": 0, "validation_failed": 0, "unsupported": 0, "error": 0},
    }

    for sp in specs:
        spec = VariantSpec.from_dict(yaml.safe_load(sp.read_text()))
        base_task_dir = args.base / spec.base_task / "environment" / "data"
        out_dir = args.out / spec.name / "environment" / "data"
        r = build_variant(spec, base_task_dir, out_dir)
        checks = [{"kind": c.kind, "passed": c.passed, "detail": c.detail} for c in (r.checks or [])]
        entry = {"base_task": spec.base_task, "expected_behavior": spec.expected_behavior,
                 "emitted": r.emitted, "error": r.error, "checks": checks}
        if r.emitted:
            entry["checksum"] = _dir_checksum(out_dir)
            manifest["summary"]["emitted"] += 1
            status = "OK"
            # On-demand: if this variant's data is heavy, keep the gate proof but
            # drop the bytes — regenerable deterministically from the spec.
            if args.skip_heavy_mb > 0:
                mb = sum(f.stat().st_size for f in out_dir.rglob("*") if f.is_file()) / 1e6
                if mb > args.skip_heavy_mb:
                    import shutil as _sh
                    _sh.rmtree(args.out / spec.name)
                    entry["materialize_on_demand"] = True
                    entry["data_mb"] = round(mb)
                    status = f"OK (on-demand, {round(mb)}MB not stored)"
        else:
            err = r.error or ""
            key = ("validation_failed" if "validation_failed" in err else
                   "unsupported" if "unsupported_format" in err else "error")
            manifest["summary"][key] += 1
            status = err.split(":")[0] or "FAIL"
        manifest["variants"][spec.name] = entry
        print(f"  {'✓' if r.emitted else '✗'} {spec.name:28} {status}")

    (args.out / "MANIFEST.json").write_text(json.dumps(manifest, indent=2))
    s = manifest["summary"]
    print(f"\nemitted {s['emitted']}/{len(specs)}  "
          f"(validation_failed={s['validation_failed']} unsupported={s['unsupported']} error={s['error']})")
    print(f"manifest: {args.out / 'MANIFEST.json'}")
    if rev_ok is False:
        print("NOTE: generated against a non-pinned dataset revision — see warning above.")


if __name__ == "__main__":
    main()
