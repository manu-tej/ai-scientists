"""Apply perturbation Ops to a variant data directory via format adapters."""
from __future__ import annotations

from pathlib import Path

from .adapters import get_adapter, AnnDataAdapter
from .spec import Op


def _sheets(params: dict) -> list:
    if "sheets" in params:
        return params["sheets"]
    return [params.get("sheet")]  # [None] for csv


def apply_op(op: Op, data_dir: Path) -> None:
    p = Path(data_dir) / op.params["file"]
    if not p.exists():
        raise FileNotFoundError(f"op target missing: {p}")
    ad = get_adapter(p)
    k = op.kind
    hr = op.params.get("header_row", 0)

    if k == "drop_columns":
        cols = op.params["columns"]
        if isinstance(ad, AnnDataAdapter):
            ad.drop_obs_columns(cols)
        else:
            for sh in _sheets(op.params):
                ad.drop_columns(cols, sheet=sh, header_row=hr)

    elif k == "drop_columns_matching":
        pat = op.params["pattern"]
        if isinstance(ad, AnnDataAdapter):
            ad.drop_obs_columns_matching(pat)
        else:
            sheets = ad.sheet_names() if op.params.get("scope") == "all_sheets" else _sheets(op.params)
            for sh in sheets:
                ad.drop_columns_matching(pat, sheet=sh, header_row=hr)

    elif k == "subset_to_single_group":
        ad.keep_rows_where(op.params["column"], [op.params["keep_value"]],
                           sheet=op.params.get("sheet"), header_row=hr)

    elif k == "drop_rows_by_value":
        ad.keep_rows_where(op.params["column"], op.params["keep_values"],
                           sheet=op.params.get("sheet"), header_row=hr)

    elif k == "anonymize_column":
        if not isinstance(ad, AnnDataAdapter):
            raise ValueError("anonymize_column currently supported only for h5ad obs columns")
        ad.anonymize_obs_column(op.params["column"], op.params.get("prefix", "id_"))

    elif k == "reduce_n":
        ad.reduce_rows(op.params["n"], op.params.get("seed", 0),
                       sheet=op.params.get("sheet"), header_row=hr)

    else:
        raise ValueError(f"unknown op kind: {k!r}")
