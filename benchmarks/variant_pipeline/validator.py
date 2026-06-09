"""The unanswerability gate: assert the answer-critical signal is truly absent.

Every SignalCheck must pass for a variant to be emitted. This is the component
whose absence let 6/11 hand-built variants ship broken.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .adapters import get_adapter, AnnDataAdapter
from .spec import SignalCheck, VariantSpec


@dataclass
class CheckResult:
    kind: str
    passed: bool
    detail: str


def _all_columns(ad, params: dict) -> list[tuple[str, str]]:
    """Return (sheet, column) pairs in scope."""
    hr = params.get("header_row", 0)
    if isinstance(ad, AnnDataAdapter):
        return [("obs", c) for c in ad.obs_columns()]
    scope = params.get("scope", "sheet")
    sheets = ad.sheet_names() if scope == "all_sheets" else [params.get("sheet")]
    out = []
    for sh in sheets:
        try:
            for c in ad.list_columns(sheet=sh, header_row=hr):
                out.append((sh, str(c)))
        except Exception:
            continue
    return out


def _scan_all_files(data_dir: Path, pat, include_instruction: bool) -> list[str]:
    """Scan EVERY file in the task surface for a leaked signal — the failure the
    per-file checks miss (sibling barcodes.tsv, an undropped peak file, the
    GSM->condition mapping printed in instruction.md). Big binaries are scanned
    cheaply or skipped: h5ad -> obs category values only; files > cap -> skipped
    (matrices don't carry the categorical label we're hunting)."""
    import pandas as pd
    from .adapters import _XLSX_READ_ENGINE, UnsupportedFormat
    SIZE_CAP = 200 * 1024 * 1024
    TABULAR = (".csv", ".tsv", ".txt", ".diff", ".xls", ".xlsx", ".gz")
    hits: list[str] = []
    for f in sorted(Path(data_dir).rglob("*")):
        if not f.is_file():
            continue
        ext = f.suffix.lower()
        if ext == ".h5ad":                          # obs labels only — never the matrix
            try:
                ad = AnnDataAdapter(f)
                for c in ad.obs_columns():
                    if any(pat.search(str(v)) for v in ad.obs_category_values(c)):
                        hits.append(f"{f.name}:obs[{c}]")
            except Exception:
                pass
            continue
        if f.stat().st_size > SIZE_CAP:             # skip giant matrices (.mtx etc.)
            continue
        if ext in TABULAR:
            try:
                ad = get_adapter(f)
                if getattr(ad, "is_excel", False):
                    for sh in ad.sheet_names():
                        df = pd.read_excel(f, sheet_name=sh, header=None, dtype=str, engine=_XLSX_READ_ENGINE)
                        if any(pat.search(str(v)) for v in df.values.ravel() if v == v):
                            hits.append(f"{f.name}:{sh}")
                else:
                    if any(pat.search(str(v)) for row in ad._rows() for v in row):
                        hits.append(f.name)
                continue
            except (UnsupportedFormat, Exception):
                pass
        try:                                        # any other text file under the cap
            if pat.search(f.read_text(errors="ignore")):
                hits.append(f.name)
        except Exception:
            pass
    if include_instruction:                         # variant root = <task>/environment/data -> ../../instruction.md
        instr = Path(data_dir).parent.parent / "instruction.md"
        try:
            if instr.exists() and pat.search(instr.read_text(errors="ignore")):
                hits.append("instruction.md")
        except Exception:
            pass
    return hits


def _eval(check: SignalCheck, data_dir: Path) -> CheckResult:
    k = check.kind

    # --- whole-surface leak scan: the signal must not survive in ANY data file
    # (sibling tables, undropped artifacts) NOR in instruction.md. Catches the
    # largest leak class — perturbing the named table while the axis re-appears
    # in a file (or the prompt) the per-file checks never look at. ---
    if k == "no_signal_anywhere":
        pat = re.compile(check.params["pattern"])
        hits = _scan_all_files(Path(data_dir), pat, check.params.get("include_instruction", True))
        return CheckResult(k, not hits,
                           "no signal leaks anywhere" if not hits else f"LEAK in: {hits[:6]}")

    # --- file-LEVEL check: the answer-critical group must not survive in any
    # filename (pairs with the anonymize_filenames op). ---
    if k == "no_filename_matching":
        pat = re.compile(check.params["pattern"])
        hits = [f.name for f in Path(data_dir).glob(check.params["glob"])
                if f.is_file() and pat.search(f.name)]
        return CheckResult(k, not hits,
                           "no filename leaks the group" if not hits else f"LEAK filenames: {hits[:5]}")

    p = Path(data_dir) / check.params["file"]

    # --- text LINE check (gzip-transparent): assert no line carries the leaked
    # label (pairs with drop_lines_matching for GEO series_matrix/SOFT etc.). ---
    if k == "no_line_matching":
        import gzip
        pat = re.compile(check.params["pattern"])
        opener = (lambda: gzip.open(p, "rt")) if p.suffix.lower() == ".gz" else (lambda: open(p))
        with opener() as fh:
            hits = [ln.strip()[:80] for ln in fh if pat.search(ln)]
        return CheckResult(k, not hits,
                           "no line leaks the label" if not hits else f"LEAK lines: {hits[:3]}")

    ad = get_adapter(p)
    hr = check.params.get("header_row", 0)

    if k == "no_column_matching":
        pat = re.compile(check.params["pattern"])
        hits = [f"{sh}:{c}" for sh, c in _all_columns(ad, check.params) if pat.search(c)]
        return CheckResult(k, not hits,
                           "no matching column" if not hits else f"FOUND: {hits}")

    if k == "column_absent":
        col = check.params["column"]
        present = [c for _, c in _all_columns(ad, check.params)]
        return CheckResult(k, col not in present,
                           f"{col!r} absent" if col not in present else f"{col!r} STILL PRESENT")

    if k == "single_value_in":
        col = check.params["column"]
        maxd = check.params.get("max_distinct", 1)
        if isinstance(ad, AnnDataAdapter):
            vals = ad.obs_category_values(col)
        else:
            vals = ad.column_values(col, sheet=check.params.get("sheet"), header_row=hr)
        distinct = sorted(set(vals))
        return CheckResult(k, len(distinct) <= maxd,
                           f"{len(distinct)} distinct ({distinct[:5]})")

    if k == "no_value_matching":
        col = check.params["column"]
        pat = re.compile(check.params["pattern"])
        if isinstance(ad, AnnDataAdapter):
            vals = ad.obs_category_values(col)
        else:
            vals = ad.column_values(col, sheet=check.params.get("sheet"), header_row=hr)
        hits = [v for v in set(vals) if pat.search(str(v))]
        return CheckResult(k, not hits,
                           "no leaking value" if not hits else f"LEAK: {hits[:5]}")

    if k == "max_rows":
        n = ad.n_rows(sheet=check.params.get("sheet"), header_row=hr)
        mx = check.params["max"]
        return CheckResult(k, n <= mx, f"n_rows={n} (max {mx})")

    if k == "no_cell_matching":
        # Scan EVERY cell for a leaked answer VALUE (handles messy/positional
        # headers AND cross-sheet value leaks where the signal is derivable from
        # another sheet's column values, not its header). scope=all_sheets scans
        # every sheet of an Excel file.
        import pandas as pd
        from .adapters import _XLSX_READ_ENGINE
        pat = re.compile(check.params["pattern"])
        cells: set = set()
        if getattr(ad, "is_excel", False):
            sheets = ad.sheet_names() if check.params.get("scope") == "all_sheets" else [check.params.get("sheet")]
            for sh in sheets:
                df = pd.read_excel(p, sheet_name=sh, header=None, dtype=str, engine=_XLSX_READ_ENGINE)
                cells |= {str(v) for v in df.values.ravel() if v == v}
        else:
            cells = {v for row in ad._rows() for v in row}
        hits = [c for c in cells if pat.search(c)]
        return CheckResult(k, not hits,
                           "no leaking cell" if not hits else f"LEAK cells: {hits[:5]}")

    return CheckResult(k, False, f"unknown check kind {k!r}")


def validate(spec: VariantSpec, data_dir: str | Path) -> list[CheckResult]:
    """Run every required_signal check. All must pass for the variant to be valid."""
    return [_eval(c, Path(data_dir)) for c in spec.required_signal]
