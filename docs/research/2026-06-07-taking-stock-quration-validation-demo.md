# Taking stock: the eval work, and the quration validation + demo plan

**Date:** 2026-06-07
**Thesis:** We have run enough evaluations. The through-line of all of them is a single,
defensible claim — **static accuracy can't measure whether a biomedical AI is trustworthy,
and an LLM grading itself is not validation.** That insight is exactly what turns quration
from "another AI bio assistant" into something with a real moat: **quration is the product;
ai-scientists is the proof.** This document takes stock of what we learned and lays out the
plan to combine them into a credible, demo-able validation loop.

---

## 1. What the evals taught us (stock-take)

Four strands, one conclusion. (All eval numbers are collated in [`results/`](../../results/).)

**(a) 3-agent BixBench-Verified-50 runs** (`docs/research/2026-06-05-bixbench-verified-50-results.md`)
- On a frozen accuracy benchmark, frontier agents are **statistically indistinguishable**:
  paired-difference 95% CIs for cc/agy/codex all cross zero (cc−agy differ on 4 of 48 tasks).
- **Capability ≠ consistency**: cc most capable (0.847), agy most consistent (0.986). The
  accuracy ranking and the reliability ranking disagree.
- **Three verifier bugs** (thousands-comma, sci-notation, fraction-numerator) each scored
  *correct* answers as 0 — automated verifiers are a systematic false-negative source.
- When agents fail, they fail **together** on a defensible reading the answer key rejects
  (bix-54-q7 monoculture anchors; bix-16-q1 DepMap sign convention — proven by reproduction).
  Per-agent consistency is blind to this; only cross-agent agreement catches it.

**(b) 3-agent BiomniBench-DA runs** (collated in [`results/biomnibench/`](../../results/biomnibench/))
- **Complete neutral rejudge**: MiniMax-M3 over all 50 tasks ranks cc 0.806 > codex 0.737 >
  agy 0.494. Gemini artifacts are complete for cc/agy but partial for codex (5/50 non-null
  task medians), so the old Gemini codex 0.770 value should be treated as a partial
  judge-effect datapoint, not a full-ranking flip.
- **Capability ≠ consistency**: codex is the *steadiest* agent (mean per-task SD 0.002) but not
  the most capable; cc is most capable (MiniMax) but least consistent (0.077).
- **Refusal/abstention is not yet validated**: the sabotaged-data refusal screen flags possible
  fabrication and partial-hedge behavior, but those labels still need manual validation and
  reconciliation with the older consolidated refusal provenance. Treat this as the next
  high-priority validation axis, not as a demo-ready result.

**(c) Deep research, 2024–2026** (`docs/research/2026-06-05-scientific-eval-design-deep-research.md`)
- The field agrees: BixBench MCQ ≈ random, AstaBench end-to-end discovery floors ~5%,
  FIRE-Bench F1 SDs ±23–47 swamp between-agent gaps.
- The fix is **temporal/replication** answer keys + **process/calibration** scoring +
  **cost-Pareto/variance** reporting. Contamination control via prompting *fails* (~30%); only
  programmatic date-restricted retrieval works. LLM-judge reliability is almost never
  human-anchored (only FIRE-Bench reports F1 0.89 vs humans).

**(d) Gathering recipes** (shipped, in quration `recipes/`, commit `e5adc4b`)
- Five key-free recipes (GEO, PubMed, bioRxiv/medRxiv, ClinicalTrials.gov, PRIDE) surface
  candidate datasets/papers into one uniform **curation manifest**, with `--since` post-cutoff
  filtering. This is the **dataset-sourcing front-end** for the validation loop below.

**Conclusion:** trust is the axis that matters, accuracy benchmarks can't see it, and
self-LLM-judging is not validation.

---

## 2. The reframe: quration's "92.5%" has to go

quration's headline validation — **92.5% LLM-as-judge** (Claude judging Claude's
interpretation) — is **circular and indefensible**, and is exactly the failure mode the work
above debunks: no human anchor, no κ, no ground truth. A working bioinformatician (the target
user) dismisses it instantly. It must be replaced by validation an LLM-judge cannot give:

| Real validation axis | How |
|---|---|
| Reaches the **published finding**? | ground truth = the paper's actual conclusion (replication-as-eval, claim-entailment F1) |
| **Calibrated** confidence? | does the ConfidenceGauge track correctness? (ECE/Brier) |
| **Abstains** appropriately? | refusal-vs-fabrication on unanswerable inputs |
| **Consistent** across reruns? | K-rep stability (`grade_reps`) |
| **Human-anchored**? | a small expert-agreement sample (κ) on a subset |

---

## 3. The synthesis: product + proof → demo

> **quration = the product** (interpret bio data, with trust UI: TrustBadge / EvidenceCard /
> ConfidenceGauge). **ai-scientists = the proof** (contamination-controlled,
> published-finding-anchored evaluation). The eval is the **moat and the credibility** —
> nobody else shows it.

ai-scientists is not bolted on cosmetically; it is the validation layer quration is missing.

---

## 4. The validation loop (every piece already exists)

```
recipes (quration/recipes/)          quration.services.interpretation_service     ai-scientists graders
─────────────────────────────        ────────────────────────────────────────    ───────────────────────────
gather post-cutoff studies     →     interpret the raw data                  →    score vs the published finding:
(GEO/PubMed/preprint/CT.gov/PRIDE)   → answer + confidence + citations             • claim-entailment F1 (FIRE-Bench style)
--since <model-cutoff>               (the product, run headless)                   • contamination delta (with vs without
                                                                                     paper title / accession / year)
                                                                                   • calibration ECE of the ConfidenceGauge
                                                                                   • K-rep consistency (grade_reps)
                                                                                   → THIS replaces the 92.5% LLM-judge
```

- **Ground truth** = each study's *reported finding*, extracted from the paper. The new
  `paperclip` skill (full-text biomedical paper/trial search) + quration's PubMed/Europe PMC
  connectors source the paper; the finding is decomposed into atomic claims (reuse quration's
  claim-extraction + ai-scientists' entailment scorer). **Human-validate the extractor on a
  sample** (target F1 ≈ 0.89, the FIRE-Bench bar) so the ground truth itself is trusted.
- **Contamination** = v1 measures the **delta** (run each task with vs without identifying
  info; report the score drop). Programmatic date-restricted retrieval (TimeSPEC-style) is v2.
- The eval **imports/calls quration**; it does not merge into it.

---

## 5. The demo (two faces, one HF Space)

1. **Interactive interpreter** — paste a gene list / GEO accession / DEG table → cited,
   confidence-scored biological interpretation (the quration product, Gradio-wrapped).
2. **Validation scorecard** — *"On N post-cutoff studies it had never seen, quration matched
   the published finding X% (claim-entailment F1), with calibrated confidence (ECE = …), and
   abstained correctly on unanswerable inputs."* Static result + methodology, shown beside the
   live tool. **This is the differentiator a chatbot can't show.**

Lead the pitch with the scorecard + a narrow "receipts" capability (e.g. drug-repurposing-by-
biomarker: DMD → tazemetostat/nintedanib with evidence + existing-trial cross-check), not the
generic "interpret anything" framing that invites "it's just ChatGPT."

**Where/how:** Hugging Face Spaces (Gradio wrap of `interpretation_service`), API key as a
Space secret, rate-limited + input-capped + cheaper model for the public demo, seeded with 2–3
pre-loaded wow examples. Render (existing `RENDER_SETUP_GUIDE.md`) is the productiony step-up
*after* feedback validates the core.

---

## 6. v1 scope (tractable — the devil's-advocate guardrail)

- **10–20 post-cutoff studies** sourced via the recipes (mix GEO + preprints).
- Run quration's interpreter over each; score claim-entailment F1 + contamination delta +
  calibration; **human-check a handful** to anchor the entailment scorer.
- Replace the 92.5% LLM-judge number on every surface with this defensible one.
- Ship the Gradio Space with the interpreter + the scorecard.

Explicitly **not** v1: full TimeSPEC retrieval, the iOS app as the feedback vehicle, a new
custom frontend, the general multi-modal data layer (parked: `quration/.../biocanon-...md`).

---

## 7. Where things live

| Repo | Role |
|---|---|
| **quration** (`~/2026/quration`) | the **product**: `services/interpretation_service`, 32 connectors, `recipes/`, frontend, iOS. *(Note: editable venv install broke when the dir moved — `uv pip install -e .` to restore before running.)* |
| **ai-scientists** (`~/2026/ai-scientists`) | the **eval harness**: `grade_bixbench` (claim/entailment + verifiers), `grade_reps` (K-rep consistency), Harbor task infra, benchbench. Imports/calls quration; emits the scorecard. |
| **HF Space** | the **demo**: Gradio interpreter + the static validation scorecard. |

---

## 8. Open decisions & risks

- **Ground-truth extraction quality.** The validation is only as good as the extracted
  "published finding." Must human-validate the extractor (κ / F1) before trusting the number —
  otherwise we've replaced one unvalidated judge with another.
- **Study selection / survivorship.** Recipes over-fetch then curate; document what's dropped.
  Post-cutoff + data-available biases toward certain subfields — report the sampling frame.
- **Contamination realism.** The delta is honest but partial; name it as such, flag TimeSPEC v2.
- **Demo cost / abuse.** Public Space running Claude per query — rate-limit, cap input, cheap
  model, cached examples.
- **Scope discipline.** quration has a graveyard-category risk (cf. shelved `alpacabio`). The
  eval/validation moat is the antidote — keep the demo a *thin wrap + a real scorecard*, not a
  new platform.

---

## 9. Build sequence

1. Restore quration's venv (`uv pip install -e .`); confirm `interpretation_service` runs headless.
2. Curate 10–20 post-cutoff studies via the recipes → a small eval set with extracted findings.
3. Eval adapter in ai-scientists: run quration over the set → claim-entailment + contamination
   delta + calibration + consistency → scorecard JSON. Human-anchor the extractor on a sample.
4. Gradio Space: interpreter face + scorecard face; seed wow examples; deploy to HF Spaces.
5. Share the URL; collect feedback from real bioinformaticians.
