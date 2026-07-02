# BiomniBench-DA — 3-agent results

50 data-analysis tasks · 3 replicates · agents cc (Claude Opus 4.7), codex (gpt-5.5),
agy (Gemini 3.1 Pro) · complete neutral MiniMax-M3 rejudge, with partial Gemini 3.1 Pro
judge-effect artifacts.

## Capability (mean of per-task medians)

| Agent     | MiniMax-M3 judge † | Gemini judge |
| :-------- | -----------------: | -----------: |
| **cc**    |          **0.826** |        0.758 |
| **codex** |              0.758 |    0.770 *   |
| **agy**   |              0.512 |        0.495 |

† Corrected 2026-06-13 (was cc 0.806 / codex 0.737 / agy 0.494). Two defects with score impact
above MiniMax-3's ~±0.07 judge noise are reflected: da-26-2 + da-20-4 (≈ +0.5 after re-run with the
method disclosed). da-15-8 + da-4-6 rubric *bugs* were fixed in the task files but their score change
was within noise → scores left at originals. da-25-1 reverted. Ranking unchanged; only deltas >~0.15
are meaningful. See [../../docs/research/2026-06-11-rubric-fixes.md](../../docs/research/2026-06-11-rubric-fixes.md).

*Codex/Gemini is partial: 5/50 tasks have non-null Gemini grades in
`grades/biomni_codex_gemini.json`. The complete 50-task headline is therefore the MiniMax-M3
column: cc > codex > agy. The Gemini artifacts remain useful for judge-effect inspection, but
should not be read as a full 50-task Codex-vs-cc ranking.

## Consistency (mean per-task SD across 3 reps; lower = steadier)

| Agent     | mean SD (lower = steadier) |
| :-------- | -------------------------: |
| **codex** |                  **0.002** |
| **agy**   |                      0.064 |
| **cc**    |                      0.077 |

(codex's 0.002 = near-identical reruns.)

**Capability ≠ consistency:** codex is the *steadiest* agent but not the most capable; cc is
most capable (MiniMax) but the *least* consistent. Accuracy and reliability rank differently.

## Refusal screen (`refusal/`)

Tasks where a critical column / sample size / p-values were removed, so the correct response is
*"this can't be answered."* The early screen below is retained as an error-analysis queue, not as
a headline benchmark result.

| Agent     |   n | Fabrication | Partial hedge | Appropriate refusal, early screen |
| :-------- | --: | ----------: | ------------: | -------------------------------: |
| **codex** |   9 |     5 (56%) |             4 |                            **0** |
| **cc**    |   5 |     2 (40%) |             3 |                            **0** |

The consolidated Gemini re-judge changes the public framing: refusals are rare, not zero. By
per-variant majority, `refusal/refusal_consolidated.json` reports cc 1/8 variants and codex 2/9
variants as appropriate refusals. The dominant failure remains partial acknowledgment followed by
an answer, with variant-specific fabrication.

## Files

- `grades/biomni_<agent>_<judge>.json` — per-task 3-rep grades (median, sd, per-rep norms);
  MiniMax-M3 files are complete for all three agents, while `biomni_codex_gemini.json` has
  5/50 non-null task medians.
- `refusal/refusal_classifications.json` — early per-response refusal screen + reason.
- `refusal/refusal_consolidated.json` — consolidated Gemini re-judge and current cleaned
  per-variant majority counts.
- `failure_analysis.xlsx` — derived manual/LLM-assisted failure-mode workbook. Use as
  working error analysis, not as independent benchmark ground truth.
- `summary.json` — the numbers above, machine-readable.

Raw run trees are not included in this public-candidate result folder. Release a scrubbed,
intentional run bundle separately if raw traces are needed for reproduction.
