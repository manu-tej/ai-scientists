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


def _eval(check: SignalCheck, data_dir: Path) -> CheckResult:
    p = Path(data_dir) / check.params["file"]
    ad = get_adapter(p)
    k = check.kind
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
        pat = re.compile(check.params["pattern"])
        cells: set = set()
        if getattr(ad, "is_excel", False):
            sheets = ad.sheet_names() if check.params.get("scope") == "all_sheets" else [check.params.get("sheet")]
            for sh in sheets:
                df = pd.read_excel(p, sheet_name=sh, header=None, dtype=str)
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
