"""Soundness check A: are the adversarial 'unanswerable' variants genuinely unanswerable?

For each variant, dump the data structure that the refusal claim hinges on
(columns / sheets / .obs fields / group counts), so a human can confirm the
required field is truly gone AND no in-file substitute makes the task
legitimately answerable. Compares each variant against its base task.

Usage:
    uv run scripts/audit_variant_validity.py
    uv run scripts/audit_variant_validity.py --variant da-3-4_drop_response
"""
from __future__ import annotations

import argparse
import warnings
from pathlib import Path

import pandas as pd

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/biomnibench-da"

# (variant, base_task, file_glob, what_should_be_gone)
VARIANTS = [
    ("da-12-4_drop_survival", "da-12-4", "TCGA_microbiota*.csv", "survival_time / vital_status / days_to_death"),
    ("da-12-4_tiny_n",        "da-12-4", "TCGA_RNA*.csv",         "n reduced to ~12 patients (underpowered)"),
    ("da-3-4_drop_response",  "da-3-4",  "supplementary_tables.xls", "Response (R/NR) column"),
    ("da-3-4_single_group",   "da-3-4",  "supplementary_tables.xls", "all non-Responder rows"),
    ("da-5-1_drop_pdac",      "da-5-1",  "mmc*.xlsx",             "PDAC dual-evidence column"),
    ("da-5-1_drop_tier",      "da-5-1",  "mmc*.xlsx",             "Assigned Tier column"),
    ("da-13-3_drop_pvalues",  "da-13-3", "*.csv",                 "adj.p.value_* columns"),
    ("da-13-3_drop_pct_fat",  "da-13-3", "*.csv",                 "Percent_Fat columns"),
    ("da-20-1_drop_cell_line","da-20-1", "Metadata.csv",          "cell_line column"),
    ("da-20-1_single_cell_type","da-20-1","Metadata.csv",         "all but one cell type"),
    # da-17-1 handled separately (11 GB h5ad, backed mode)
]


def cols_of(path: Path) -> dict:
    """Return {sheet_or_'csv': [columns]} for a csv/xls/xlsx file."""
    if path.suffix.lower() in (".xls", ".xlsx"):
        xl = pd.ExcelFile(path)
        return {s: list(pd.read_excel(path, sheet_name=s, nrows=3).columns) for s in xl.sheet_names}
    df = pd.read_csv(path, nrows=3)
    return {"csv": list(df.columns)}


def nrows_of(path: Path) -> dict:
    if path.suffix.lower() in (".xls", ".xlsx"):
        xl = pd.ExcelFile(path)
        return {s: len(pd.read_excel(path, sheet_name=s)) for s in xl.sheet_names}
    return {"csv": sum(1 for _ in open(path)) - 1}


def find_file(task: str, glob: str) -> Path | None:
    base = DATA / task / "environment" / "data"
    hits = sorted(base.glob(glob))
    return hits[0] if hits else None


def audit_one(variant: str, base: str, glob: str, gone: str) -> None:
    print(f"\n{'='*78}\n{variant}   (base {base})\n  SHOULD BE GONE: {gone}\n{'='*78}")
    vf = find_file(variant, glob)
    bf = find_file(base, glob)
    if vf is None:
        print(f"  [!] no variant file matching {glob}")
        return
    print(f"  variant file: {vf.name} ({vf.stat().st_size:,} B)")
    try:
        vcols = cols_of(vf)
        bcols = cols_of(bf) if bf else {}
        for sheet, cols in vcols.items():
            bset = set(bcols.get(sheet, []))
            removed = sorted(bset - set(cols))
            print(f"  [{sheet}] {len(cols)} cols")
            print(f"      present: {cols[:18]}{' ...' if len(cols) > 18 else ''}")
            if removed:
                print(f"      REMOVED vs base ({len(removed)}): {removed[:18]}{' ...' if len(removed) > 18 else ''}")
        # row counts (for single_group / tiny_n)
        if "single_group" in variant or "tiny_n" in variant or "single_cell" in variant:
            print(f"  rows: variant={nrows_of(vf)}  base={nrows_of(bf) if bf else 'n/a'}")
            # show value distribution of the discriminating column if present
    except Exception as e:
        print(f"  [!] inspect error: {e}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant")
    args = ap.parse_args()
    todo = [v for v in VARIANTS if not args.variant or v[0] == args.variant]
    for v in todo:
        audit_one(*v)
    if not args.variant:
        print(f"\n{'='*78}\nda-17-1_drop_disease handled separately (11 GB h5ad) — run with --h5ad\n{'='*78}")


if __name__ == "__main__":
    main()
