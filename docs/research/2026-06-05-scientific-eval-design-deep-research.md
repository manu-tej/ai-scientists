# Building scientific-agent evals for real working conditions — deep research

**Date:** 2026-06-05
**Question:** How to build evals/benchmarks for AI agents that capture real working-scientist
conditions — continuously arriving data, knowledge still being discovered/revised, pervasive
uncertainty, no fixed answer key. Bio-centered, ML-informed.
**Method:** fan-out search (6 angles) → 30 primary sources → 141 claims → 25 adversarially
verified (2/3-refute kill rule) → 23 confirmed. Prioritized 2024–2026.

## TL;DR

Abandon the frozen exact-match gold key. Three combinable, 2024–2026-validated strategies:

1. **Temporal / prospective answer keys** — score against the *future*, which can't leak.
   ForecastBench (future-only events, self-refreshing) and replication/rediscovery-as-eval
   (ReplicationBench, FIRE-Bench: give raw post-cutoff data, mask the methods, score whether
   the agent independently reaches the published finding).
2. **Process + calibration scoring without ground truth** — claim-decomposition + semantic-
   entailment P/R/F1 (human-validated F1 ≈ 0.89), rubric LLM-judge, two-axis
   *faithfulness-vs-correctness*.
3. **Cost-aware Pareto + run-to-run variance reporting** — because single-number accuracy
   provably fails to separate frontier agents and is gameable by burning compute.

The dominant pitfall: **prompt-based contamination control doesn't work** (telling a model
"don't use post-cutoff info" cuts leakage only ~30%). Honest backtesting needs *programmatic*
date-restricted retrieval, and leakage must be importance-weighted.

## Verified findings (with citations)

### 1. Static accuracy can't separate frontier scientific agents *(high confidence)*
Floor effects, near-random scores, and run-to-run variance that swamps between-agent gaps.
- **BixBench** [arXiv:2503.00096]: best open-answer **17%**, MCQ **no better than random**
  (~25%), gameable by a refusal option, no gain from majority voting.
- **AstaBench** [arXiv:2510.21652, 57 agents/22 classes]: best open agent 53.0%, best
  open-weight 11.1%, **end-to-end discovery max ~5%** (compounding ≈0.7¹⁰), data analysis max 34%.
- **FIRE-Bench** [arXiv:2602.02905]: strongest agent F1 **46.7 ± 23.4**, per-task SDs up to
  **±40–47** — "high run-to-run variance… concerns about reproducibility."
> This *independently reproduces tonight's bootstrap result*: our cc/agy/codex CIs all crossed
> zero. The field is converging on the same conclusion. (BixBench interpretive gloss was a 2-1
> vote; the numbers are verbatim-confirmed.)

### 2. Prospective forecasting = structurally contamination-proof, self-refreshing *(high)*
**ForecastBench** [arXiv:2409.19839, ICLR 2025, Tetlock et al.]: "comprised solely of questions
about future events that have no known answer at the time of submission." Auto-refreshes ~1,000
questions on a schedule; resolves continuously; scored by **Brier**. Human superforecasters
(0.096) significantly beat the best LLM (Claude 3.5 Sonnet, 0.122, p<0.001) on a matched subset.
*Caveat: geopolitics/economics, not bio — the mechanism transfers, the demonstrated gap doesn't.*

### 3. Replication/rediscovery-as-eval gives a contamination-resistant key *(high)*
Hand the agent only raw data + a high-level question, **mask the methods/design/conclusions**,
score reaching the published finding.
- **ReplicationBench** [arXiv:2510.24591]: 19 astro papers / 107 author-co-developed tasks;
  best models **<20%**; memorization <9%; unmasking inflates scores 15–20%.
- **FIRE-Bench** [arXiv:2602.02905]: masks methodology of 2024–25 ML papers, "constrained
  rediscovery"; no consistent pre/post-cutoff advantage (honest null).
- **Biomni** [bioRxiv 2025.05.30.656746]: the bio analog — testable protocols judged by blinded
  experts + n=1 wet-lab validation (low power; the point is the eval *type*).

### 4. Scoring without a frozen key — three validated mechanisms *(high)*
- **Claim decomposition + LLM semantic-entailment → P/R/F1** (RAGChecker-style). FIRE-Bench's
  scorer **human-validated at P 0.95 / R 0.86 / F1 0.89**.
- **Rubric + LLM-as-judge** per problem (AstaBench).
- **Two-axis: faithfulness (method adherence) vs correctness (result)** (ReplicationBench).
- Held-out *quantitative* metrics as the leak-proof complement: **BioML-bench**
  [bioRxiv 2025.09.01.673319] grades by hidden AUROC/Spearman, not exact-match; **LAB-Bench**
  [arXiv:2407.10362] anchors "good" to human expert biologists.

### 5. Contamination control: prompting fails; verify programmatically *(high)*
[arXiv:2602.17234 "All Leaks Count, Some Count More"]: "Only use information before [date]"
cut leakage just **~30%** (model still cited earnings 3 days post-cutoff). **TimeSPEC**
(external pre-cutoff search + explicit date comparison) → 99% reduction. Illusory baselines:
COVID-era stock ranking scored Spearman 0.52 via leakage, honest score 0.167. Leakage must be
**importance-weighted** (Shapley-DCLR) — some leaked claims drive the decision, others are inert.

### 6. Cost-aware Pareto + time-invariant cost is the recommended replacement *(high)*
**AstaBench** [arXiv:2510.21652 + allenai.org/blog/astabench]: normalized $ cost from a frozen
litellm snapshot (fair as prices change), score-vs-cost Pareto frontier. Motivation: "even
simplistic strategies, such as majority vote over repeated invocation, can boost accuracy by
burning cash." Plus a production literature corpus with date-restricted retrieval.

## Buildable blueprint — a biomedical reliability eval with no frozen gold

Port the validated non-bio mechanisms onto bio data:

| Layer | Mechanism | Bio instantiation |
|---|---|---|
| **Temporal key** | future-only / masked-paper rediscovery | post-cutoff bioRxiv/medRxiv papers: give raw supplementary data + masked question, score reaching the reported finding; prospective GWAS/clinical-trial/perturbation replication scored on resolution |
| **Scoring** | claim-entailment P/R/F1 + rubric judge, two-axis | decompose agent conclusion → atomic claims → entailment vs the paper's reported claims; grade *faithfulness* (sound method) separately from *correctness* |
| **Calibration** | confidence elicitation → ECE/Brier/AUROC | require a confidence per numeric claim; score whether confidence tracks entailment-correctness |
| **Refusal** | unanswerable-task design | drop a critical column / sub-threshold n / wrong modality; score refusal-vs-fabrication |
| **Robustness** | K-rep consistency + perturbation + data-influx | rerun (K≥10), column-rename / NaN / ID-swap, feed data in installments; measure conclusion stability |
| **Contamination** | programmatic date-restricted retrieval, Shapley-weighted leakage | external pre-cutoff-only search; importance-weight any leaked claim |
| **Reporting** | cost-aware Pareto + variance | score-vs-cost frontier, per-task SDs, paired CIs (never a bare ranking) |

## Caveats

- **Domain transfer:** the strongest temporal/replication evidence is **non-bio** (ForecastBench
  geopolitics, ReplicationBench astro, FIRE-Bench general ML). Bio-centered evidence (Biomni,
  BixBench, BioML-bench, LAB-Bench) is thinner — these are transferable *methodology*, not bio
  benchmarks.
- **Time-sensitivity:** absolute numbers (BixBench 17%, AstaBench floors, FIRE-Bench F1) are
  tied to 2024–25 models and will stale; the *structural* findings (non-separation, prompt-
  leakage failure, variance) are durable.
- **Source strength:** AstaBench's primary is an author blog (corroborated by arXiv); the
  leakage paper (2602.17234) and FIRE-Bench (2602.02905) are Feb-2026 preprints near the
  knowledge cutoff. Split votes (2-1) on BixBench gloss, FIRE-Bench contamination-resistance,
  Shapley weighting — dissent was on interpretation, not the numbers.
- **LLM-judge validation:** only FIRE-Bench reports human agreement (F1 0.89); κ-reliability of
  the AstaBench/ReplicationBench judges is asserted, not characterized.

## Open questions (gaps = opportunity for this project)

1. What does a fully **bio-centered prospective key** look like (pre-registered trial outcomes,
   recent GWAS/perturbation replication, future target validation) — resolution latency &
   survivorship controls for a self-refreshing bio benchmark?
2. How reliable are **LLM-judge / entailment scorers on biomedical claims** (jargon, quantitative
   thresholds, contested nomenclature)? What κ gates their use vs held-out AUROC/Spearman?
3. **Calibration/abstention is under-served in bio** — no surviving bio benchmark cleanly
   operationalizes ECE / refusal-vs-fabrication / unanswerable-task design. *Open lane.*
4. How to measure **robustness-under-data-influx** concretely (installment stability,
   perturbations) and which reliability framework (Rabanser metrics, K-rep consistency) fits bio.

## Two claims that were refuted (kept for honesty)
- AstaBench per-benchmark explicit date-cutoff enumeration — overstated (1-2).
- A specific "LAB-Bench = 2,400 MCQ / 5 categories" description — numbers didn't hold (0-3).

## Primary sources
BixBench arXiv:2503.00096 · AstaBench arXiv:2510.21652 + allenai.org/blog/astabench · Biomni
bioRxiv:2025.05.30.656746 · LAB-Bench arXiv:2407.10362 · BioML-bench bioRxiv:2025.09.01.673319 ·
ForecastBench arXiv:2409.19839 · ReplicationBench arXiv:2510.24591 · FIRE-Bench arXiv:2602.02905 ·
Contamination/leakage arXiv:2602.17234 · Rabanser reliability arXiv:2602.16666 · LiveCodeBench
arXiv:2403.07974 · abstention survey (TACL Know Your Limits) · plus calibration/refusal &
instrument-validity sources (see run wf_fcee7c97-8e8).
