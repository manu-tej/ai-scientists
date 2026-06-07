# BiomniBench-DA — 3-agent results

50 data-analysis tasks · 3 replicates · agents cc (Claude Opus 4.7), codex (gpt-5.5),
agy (Gemini 3.1 Pro) · graded by neutral MiniMax-M3 **and** Gemini 3.1 Pro (judge-effect study).

## Capability (median of per-task medians)

| Agent     | Gemini judge | MiniMax judge |
| :-------- | -----------: | ------------: |
| **cc**    |        0.758 |     **0.806** |
| **codex** |    **0.770** |         0.737 |
| **agy**   |        0.495 |         0.494 |

**The judge flips the cc-vs-codex ranking** (Gemini: codex > cc; MiniMax: cc > codex); agy is
clearly last under both. This is the judge-dependence finding — the same number you'd headline
depends on who grades.

## Consistency (mean per-task SD across 3 reps; lower = steadier)

| Agent     | mean SD (lower = steadier) |
| :-------- | -------------------------: |
| **codex** |                  **0.002** |
| **agy**   |                      0.064 |
| **cc**    |                      0.077 |

(codex's 0.002 = near-identical reruns.)

**Capability ≠ consistency:** codex is the *steadiest* agent but not the most capable; cc is
most capable (MiniMax) but the *least* consistent. Accuracy and reliability rank differently.

## Refusal under sabotaged data (`refusal/`)

Tasks where a critical column / sample size / p-values were removed, so the correct response is
*"this can't be answered."* Classification of each response:

| Agent     |   n | Fabrication | Partial hedge | Appropriate refusal |
| :-------- | --: | ----------: | ------------: | ------------------: |
| **codex** |   9 |     5 (56%) |             4 |               **0** |
| **cc**    |   5 |     2 (40%) |             3 |               **0** |

**Refusal collapse: zero appropriate refusals.** Every response either fabricated data (e.g.
reconstructing dropped cell types from marker genes; fetching survival data from the GDC API to
fill a removed column) or partially hedged while still reporting confident numbers. Frontier
agents essentially never abstain even when the data is deliberately broken — the sharpest trust
failure in the whole program.

## Files

- `grades/biomni_<agent>_<judge>.json` — per-task 3-rep grades (median, sd, per-rep norms).
- `refusal/refusal_classifications.json` — per-response refusal classification + reason.
- `refusal/refusal_consolidated.json` — canonical cc+codex refusal cells (provenance).
- `summary.json` — the numbers above, machine-readable.

Raw run trees live on serene (`/home/manu/benchbench/runs/`).
