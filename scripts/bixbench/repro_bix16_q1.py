#!/usr/bin/env python3
"""Reproduce bix-16-q1 and show it is a SIGN-CONVENTION ambiguity, not an agent error.

Question: "what gene symbol has the strongest negative Spearman correlation between its
expression and essentiality?"  Gold answer = CDKN1A.  All three agents answered CCND1.

DepMap CRISPRGeneEffect (Chronos) scores are NEGATIVE when a gene is essential, so
"essentiality" is sign-ambiguous:
  - convention A: essentiality = raw gene-effect column (neg = more essential)
        -> strongest negative corr(expression, gene_effect) = CCND1   (what the agents got;
           codex even reported rho = -0.6288254699, matching this to 7 decimals)
  - convention B: essentiality = -(gene-effect) (pos = more essential)
        -> strongest negative corr(expression, essentiality) = CDKN1A (the gold answer;
           it is the single MOST POSITIVE gene under convention A — the exact mirror)

Both readings are defensible; the agents took the literal-column reading. This is a
correlated cross-agent agreement on an ambiguous spec, not a capability failure.

Data (DepMap, provided in the capsule's CapsuleData/):
  CRISPRGeneEffect.csv                                     (cell lines x genes, essentiality)
  OmicsExpressionProteinCodingGenesTPMLogp1BatchCorrected.csv (cell lines x genes, log-TPM)

Usage:
  python scripts/bixbench/repro_bix16_q1.py --data <dir-with-the-two-csvs>
"""
from __future__ import annotations
import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import rankdata


def spearman_per_gene(expr: np.ndarray, ess: np.ndarray, min_n: int = 50) -> np.ndarray:
    """Per-column Spearman rho between expression and essentiality, pairwise-complete."""
    rho = np.full(expr.shape[1], np.nan)
    for j in range(expr.shape[1]):
        e, c = expr[:, j], ess[:, j]
        m = ~(np.isnan(e) | np.isnan(c))
        if m.sum() >= min_n:
            rho[j] = np.corrcoef(rankdata(e[m]), rankdata(c[m]))[0, 1]
    return rho


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True, type=Path,
                    help="dir containing CRISPRGeneEffect.csv + the expression CSV")
    ap.add_argument("--min-n", type=int, default=50, help="min paired cell lines per gene")
    args = ap.parse_args()

    sym = lambda c: c.split(" (")[0]  # "CDKN1A (1026)" -> "CDKN1A"
    print("loading CRISPR gene-effect (essentiality)...", flush=True)
    ess = pd.read_csv(args.data / "CRISPRGeneEffect.csv", index_col=0)
    print("loading expression...", flush=True)
    expr = pd.read_csv(
        args.data / "OmicsExpressionProteinCodingGenesTPMLogp1BatchCorrected.csv", index_col=0)

    for df in (ess, expr):
        df.columns = [sym(c) for c in df.columns]
    ess = ess.loc[:, ~ess.columns.duplicated()]
    expr = expr.loc[:, ~expr.columns.duplicated()]
    cells = ess.index.intersection(expr.index)
    genes = list(ess.columns.intersection(expr.columns))
    print(f"common: {len(cells)} cell lines, {len(genes)} genes", flush=True)

    rho = pd.Series(
        spearman_per_gene(expr.loc[cells, genes].to_numpy(np.float32),
                          ess.loc[cells, genes].to_numpy(np.float32), args.min_n),
        index=genes).dropna()

    print("\n=== convention A: essentiality = raw gene-effect (neg = more essential) ===")
    print("strongest NEGATIVE corr(expression, gene_effect):")
    print(rho.sort_values().head(8).round(4).to_string())
    print("\n=== convention B: essentiality = -(gene-effect) (pos = more essential) ===")
    print("strongest NEGATIVE corr(expression, essentiality):")
    print((-rho).sort_values().head(8).round(4).to_string())

    print("\n=== where do gold (CDKN1A) and agents (CCND1) land under convention A? ===")
    ranked = list(rho.sort_values().index)  # ascending -> most negative first
    for g in ("CDKN1A", "CCND1", "KLF5", "RNASEK"):
        if g in rho.index:
            print(f"  {g}: rho={rho[g]:+.4f}  rank among most-negative = "
                  f"{ranked.index(g) + 1}/{len(rho)}")
        else:
            print(f"  {g}: not in common genes")


if __name__ == "__main__":
    main()
