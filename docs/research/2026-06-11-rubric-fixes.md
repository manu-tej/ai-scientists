# BiomniBench-DA rubric/instruction fixes — 2026-06-11

Five tasks were confirmed as benchmark defects in the verified failure analysis
([failure_analysis.xlsx](../../results/biomnibench/failure_analysis.xlsx),
[v2 report](2026-06-11-biomnibench-failure-modes-v2.md)) and fixed here. Fix philosophy
(chosen by the benchmark owner): **disclose the required method in the instruction** for
paper-specific rubrics (keep the rubric, make it fair); **correct the rubric** for plain errors.

## What changed

| Task | Defect | Fix | File changed |
|---|---|---|---|
| **da-15-8** | rubric C1 had the two source files **swapped** (graded MOESM5 as spinal-cord, MOESM2 as CSF; instruction says the opposite) | swapped them back to match the instruction | `tests/rubric.txt` |
| **da-4-6** | rubric C1 required loading + merging **`mmc1.csv`**, which is neither staged nor mentioned (only `mmc5.csv` exists, and it has all needed columns) | rewrote C1 (4 spots) to use `mmc5.csv` only | `tests/rubric.txt` |
| **da-25-1** | question asks "clinical T stage"; rubric gates [A] on **`PATH_T_STAGE`** as primary variable | disclosed the PATH_T_STAGE / T2-vs-T3/T4 / FDR approach in the question | `instruction.md` |
| **da-20-4** | question asks "consistent or divergent?"; rubric demands **ranked GSEA vs MSigDB Hallmark + specific NES** from the (forbidden) paper figure | disclosed the DESeq2 → Hallmark-GSEA → NES pipeline | `instruction.md` |
| **da-26-2** | question names no method; rubric demands **Normality LRT → t-skew → SSD → druggable-DB → PTPN11** from the (forbidden) paper | disclosed the NLRT / t-skew / SSD / druggable-DB pipeline (without naming the answer gene) | `instruction.md` |

The method disclosures name the **methodology** only — never the answer gene/pathway/numbers
(PTPN11, KRAS/EMT/MYOGENESIS NES, TP53 OR), which the agent must still derive.

## ⚠️ Re-grade vs Re-RUN — they are NOT the same

Changing a **rubric** invalidates only the *score*; the agent's existing answer is still valid.
Changing an **instruction** invalidates the *answer itself* — the agents ran under the old (unfair)
instruction, so they must re-run the task before re-grading.

| Task | Change type | Action needed | Affected agents |
|---|---|---|---|
| da-15-8 | rubric only | **RE-GRADE** existing cap3 answers with MiniMax-3 | agy (failing); optionally cc/codex for consistency |
| da-4-6 | rubric only | **RE-GRADE** existing cap3 answers with MiniMax-3 | agy (failing); optionally cc/codex |
| da-25-1 | instruction | **RE-RUN** task (new instruction) → then re-grade | all 3 (instruction is shared) |
| da-20-4 | instruction | **RE-RUN** task → then re-grade | all 3 |
| da-26-2 | instruction | **RE-RUN** task → then re-grade | all 3 |

**Net:** 2 tasks need re-grade only (cheap, no agent compute); 3 tasks need a full re-run of the
3-agent × 3-rep matrix (9 reps each = 27 agent runs) before their scores are meaningful.

Until then, the current MiniMax-3 medians for these 5 tasks are **stale** and should be excluded
from headline capability numbers.

---

## Results — executed 2026-06-13

Re-grade (rubric-only) + re-run (instruction) completed on the private remote run worker
(canonical run `cap3`; judge = MiniMax-3 via `openrouter:minimax/minimax-m3`; Codex auth refreshed
from the current local subscription token). 3-rep medians unless noted.

| Task | Agent | OLD | NEW | verdict |
|---|---|---:|---:|---|
| da-15-8 | agy | 0.53 | **0.60** | fixed — swapped-files bug recovered C1 |
| da-4-6 | agy | 0.41 | 0.38 | ~unchanged — failure was genuine capability, **not** the mmc1 bug |
| da-26-2 | cc | 0.43 | **0.87** | fixed |
| da-26-2 | codex | 0.35 | **0.87** | fixed |
| da-26-2 | agy | 0.35 | **0.815** (2 reps) | fixed |
| da-20-4 | cc | 0.25 | **0.80** | fixed |
| da-20-4 | codex | 0.10 | **0.63** | fixed |
| da-20-4 | agy | 0.15 | **0.60** | fixed |
| da-25-1 | codex | 0.48 | 0.485 | **NOT fixed → REVERTED** |
| da-25-1 | agy | 0.29 | 0.205 | **NOT fixed → REVERTED** |

### da-25-1 reverted (mis-classified)

Disclosure did not lift da-25-1: codex *followed* the disclosed PATH_T_STAGE method but concluded
"no FDR-significant gene," while rubric C6[A] demands the exact gold result (TP53 OR=3.08, FDR=0.0379).
So da-25-1's low score is **exact-result reproduction difficulty, not a hidden-method defect** — it
was mis-classified. The instruction edit was **reverted** locally and on the run worker; da-25-1 retains its
original cap3 score as a genuine_capability failure.

### Corrected aggregate (all 50 tasks, MiniMax-3)

| Agent | mean (was) | median |
|---|---:|---:|
| cc | **0.826** (0.806) | 0.870 |
| codex | **0.758** (0.737) | 0.805 |
| agy | **0.513** (0.494) | 0.520 |

**The capability ranking is unchanged (cc > codex > agy).** The 4 defect-fixes recovered
unfairly-docked points roughly evenly (~+0.02 mean each), correcting absolute scores without
changing who wins — the ordering is robust to these defects.

### Patched

`results/biomnibench/grades/biomni_{cc,codex,agy}_minimax.json` updated for **da-15-8, da-4-6,
da-26-2, da-20-4** (8 cells), each carrying a `_corrected` block (date, reason, prior_median, judge).
Originals backed up to `*.bak-precorrection`. da-25-1 left untouched (reverted).

### Caveats

- The 4 fixed tasks are now a **different task-version** than the other 46 (fixed rubric/instruction);
  their corrected scores compare to *each other*, not to the original cap3 run for those cells.
- agy/da-26-2 delivered 2 reps (one failed); median over 2. cc/da-20-4 norms `[0.55, 0.80, 0.90]` show spread.
- "disclose the method" worked for genuine hidden-method defects (da-26-2, da-20-4) but **not** for
  exact-result-reproduction gates (da-25-1) — confirming the fix is targeted, not universal.

---

## ⚠️ MiniMax-3 judge is non-deterministic (~±0.07) — small patches reverted

While verifying the re-grade scripts, the **identical** cap3 traces were graded twice against the
**same** fixed rubric and gave different scores:

| Task | re-grade #1 | re-grade #2 | original (pre-fix) |
|---|---:|---:|---:|
| da-15-8 | 0.60 `[.6,.6,.6]` | 0.53 `[.47,.53,.53]` | 0.53 |
| da-4-6 | 0.38 | 0.465 (one rep dropped on a judge API error) | 0.41 |

So **MiniMax-3 carries ~±0.07 run-to-run noise on identical inputs** (`grade_reps.py` is single-vote).
da-15-8's "recovery" landed right back on its original 0.53 — i.e. it was never above the noise floor.

**Consequences:**
- **Only score deltas larger than ~0.15 are trustworthy** across this benchmark. da-26-2 and da-20-4
  (≈ +0.5) clear that easily and stand; da-15-8 (+0.07) and da-4-6 (−0.03) do not.
- The **da-15-8 and da-4-6 grade patches were REVERTED** to their originals (0.53, 0.41). Their rubric
  *file* fixes (swapped MOESM files; unstaged-mmc1 requirement) are kept — those were genuine bugs —
  but no score change is claimed where it is indistinguishable from noise.
- Patched cells remaining: **da-26-2, da-20-4 only.** Corrected aggregate:
  cc **0.826** / codex **0.758** / agy **0.512** (ranking unchanged; agy now reflects 2 corrected cells).
- A single MiniMax call occasionally errors and `grade_reps.py` silently drops that rep (da-4-6 → 2 reps).

**Durable fix for future datasets:** grade with **N-vote majority** to average out judge noise.
`bench/grade.py` already supports `--votes N`; `scripts/grade_reps.py` was extended with the same
`--votes` flag (default 1; each rep's norm becomes the mean of N judge draws) so the all-reps path can
be de-noised too. Use `--votes 5` for scores of record. **Verified working** (`--votes 3`): da-15-8
de-noises to ~0.58, da-4-6 to ~0.45 — both ~+0.05 over originals but still inside the noise band, so
the revert stands. (`scripts/grade_reps.py` is now in the repo; it was previously private-run-worker-only.)
