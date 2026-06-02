"""Apply perturbation Ops to a variant data directory via format adapters."""
from __future__ import annotations

import re
from pathlib import Path

from .adapters import get_adapter, AnnDataAdapter
from .spec import Op


def _sheets(params: dict) -> list:
    if "sheets" in params:
        return params["sheets"]
    return [params.get("sheet")]  # [None] for csv


def _sorted_glob(data_dir: Path, pattern: str) -> list[Path]:
    """Deterministic file list for a glob (sorted by relative posix path)."""
    return sorted((p for p in Path(data_dir).glob(pattern) if p.is_file()),
                  key=lambda p: p.relative_to(data_dir).as_posix())


def apply_op(op: Op, data_dir: Path) -> None:
    data_dir = Path(data_dir)
    k = op.kind

    # --- file-LEVEL ops (operate on filenames, not table contents) --- #
    # Some tasks encode the answer-critical group ONLY in filenames (e.g.
    # GSM..._MS08162018 vs ..._HC13 = patient vs control). No table column
    # carries it, so anonymize the names: rename every globbed file to a neutral
    # sequential id, deterministically, stripping the group token.
    if k == "anonymize_filenames":
        prefix = op.params.get("prefix", "sample_")
        files = _sorted_glob(data_dir, op.params["glob"])
        if not files:
            raise FileNotFoundError(f"anonymize_filenames matched nothing: {op.params['glob']}")
        width = max(4, len(str(len(files) - 1)))
        for i, f in enumerate(files):
            suffixes = "".join(f.suffixes)               # keep .txt.gz so adapters still work
            f.rename(f.with_name(f"{prefix}{i:0{width}d}{suffixes}"))
        return

    # Remove a whole FILE GROUP: when one arm of a comparison is encoded by which
    # files a sample lives in (e.g. sub_TCGA_* = patients vs sub_CCLE_* = cell
    # lines), no column edit can separate them — but deleting one entire arm makes
    # the between-arm comparison structurally impossible.
    if k == "drop_files_matching":
        files = _sorted_glob(data_dir, op.params["glob"])
        if not files:
            raise FileNotFoundError(f"drop_files_matching matched nothing: {op.params['glob']}")
        for f in files:
            f.unlink()
        return

    p = data_dir / op.params["file"]
    if not p.exists():
        raise FileNotFoundError(f"op target missing: {p}")

    # --- text LINE op (format-agnostic, gzip-transparent) --- #
    # For non-tabular text where the signal is a whole line, not a table column:
    # e.g. a GEO series_matrix / SOFT file where each disease-stage label is its
    # own `!Sample_characteristics_ch1 "fibrosis stage: N"` line. Delete every
    # line matching the pattern; the rest of the file is untouched.
    if k == "drop_lines_matching":
        import gzip
        pat = re.compile(op.params["pattern"])
        opener = (lambda m: gzip.open(p, m + "t")) if p.suffix.lower() == ".gz" else (lambda m: open(p, m))
        with opener("r") as fh:
            lines = fh.readlines()
        with opener("w") as fh:
            fh.writelines(ln for ln in lines if not pat.search(ln))
        return

    ad = get_adapter(p)
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
