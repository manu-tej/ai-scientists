# BiomniBench-DA — 3-agent results

50 data-analysis tasks · 3 replicates · agents cc (Claude Opus 4.7), codex (gpt-5.5),
agy (Gemini 3.1 Pro) · complete neutral MiniMax-M3 rejudge, with partial Gemini 3.1 Pro
judge-effect artifacts.

## Capability (mean of per-task medians)

| Agent     | MiniMax-M3 judge | Gemini judge |
| :-------- | ----------------: | -----------: |
| **cc**    |         **0.806** |        0.758 |
| **codex** |             0.737 |    0.770 *   |
| **agy**   |             0.494 |        0.495 |

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

## Exploratory refusal screen (`refusal/`)

Tasks where a critical column / sample size / p-values were removed, so the correct response is
*"this can't be answered."* The classifications below are **not yet validated**; treat them as
an exploratory screen and error-analysis queue, not as a headline benchmark result.

| Agent     |   n | Fabrication | Partial hedge | Appropriate refusal |
| :-------- | --: | ----------: | ------------: | ------------------: |
| **codex** |   9 |     5 (56%) |             4 |               **0** |
| **cc**    |   5 |     2 (40%) |             3 |               **0** |

The unvalidated screen suggests a concerning pattern worth adjudicating manually: responses often
continued after detecting missing data, including cases that appear to reconstruct dropped labels
or substitute external data. Do not use these counts as final refusal rates until the labels and
variant validity are independently reviewed.

## Files

- `grades/biomni_<agent>_<judge>.json` — per-task 3-rep grades (median, sd, per-rep norms);
  MiniMax-M3 files are complete for all three agents, while `biomni_codex_gemini.json` has
  5/50 non-null task medians.
- `refusal/refusal_classifications.json` — unvalidated per-response refusal screen + reason.
- `refusal/refusal_consolidated.json` — older consolidated refusal provenance; not authoritative
  until reconciled with the unvalidated screen.
- `summary.json` — the numbers above, machine-readable.

Raw run trees live on serene (`/home/manu/benchbench/runs/`).
