# BiomniBench-DA Failure-Mode Report — v2 (CORRECTED, canonical-source)

**Date:** 2026-06-11
**Scope:** Per-cell failure adjudication of three frontier agents — `cc` (Claude Opus 4.7), `codex` (gpt-5.5), `agy` (Gemini 3.1 Pro) — across the 45 lowest-scoring BiomniBench-DA cells.
**Score of record:** MiniMax-3 median on the **complete 450-run / 50-task neutral rejudge** (3 agents × 50 tasks × 3 reps = 450, grading 450/450 complete). MiniMax-3 is the **sole** score of record.
**Source:** `cc`/`codex` answers from `runs/cc_bundle.json` and `runs/codex_bundle.json` (all 50 tasks, real delivered answers); `agy` answers from `runs/harbor_base_matrix`. Every failing cell analyzed below has a real, delivered agent answer.

---

## 1. CORRECTION NOTICE

This report supersedes v1 (`2026-06-11-biomnibench-failure-modes.md`), which made two errors that inverted its headline. **(a) Wrong source:** v1 read the partial local `runs/harbor_base_matrix` copy for `cc` and `codex`, where individual replicates had hit a `403 → 429` rate-limit; v1 mislabeled those rate-limited replicates as "infrastructure"/`missing_trace` artifacts and concluded ~37% of low scores "do not measure capability." In fact those agents **did deliver** real answers — recovered here from the canonical `cc_bundle.json` and `codex_bundle.json` — so every failing cell is a genuine graded delivery, not an empty artifact. **(b) Wrong second opinion:** v1 treated an in-container secondary judge's score as a meaningful "second opinion" and labeled several failures "judge-dependent." That secondary judge is a known-unreliable inflating grader and is **excluded entirely** from this analysis; **MiniMax-3 median is the only score of record.** With both errors removed, the artifact category nearly disappears and the picture flips: the vast majority of low BiomniBench-DA scores are real.

---

## 2. TL;DR

- **Low scores are overwhelmingly real, not artifacts.** Of **45** low-scoring cells, **36 (80%) are genuine model weaknesses** and only **9 (20%) are rubric/task defects (8) or a partial-delivery deliverable gap (1)** — the inverse of v1's "half are artifacts" claim.
- **`cc` and `codex` are no longer "dead on arrival."** Both delivered complete, methodologically grounded answers on every cell once read from the canonical bundles. `cc`'s 5 lowest cells split **3 genuine capability / 2 task-design defect**; `codex`'s 8 split **5 genuine / 3 task-design**.
- **`agy` is the dominant genuine signal and a method-substitution workhorse.** **28 of its 32** lowest cells are genuine `genuine_capability` failures (mm3 0.18–0.53, median 0.41), all delivered: it consistently runs a *real-but-coarser* analysis — substituting a simpler statistic for the rubric-prescribed pipeline and skipping the highest-weight criterion — rather than crashing or refusing.
- **The 5 correlated all-agent tasks do not share one cause.** Per-agent verify verdicts split them: **da-6-2 is genuinely hard for all three** (real pipeline-substitution by each); **da-26-2, da-24-3, da-20-4, da-18-5 are task-design defects for most agents** (rubrics grade undisclosed/forbidden-paper pipelines), though a few agents independently failed them on real merits too.
- **`da-26-2` is a confirmed rubric defect (forbidden-paper pipeline).** It gates ~60–73/100 pts on a named LRT→t-skew→SSD→druggable→PTPN11 pipeline the question never describes and whose only source the instruction explicitly forbids reading — a competent on-question answer is structurally capped near 0.35.

---

## 3. Corrected Taxonomy — `failure_layer` × agent

All 45 cells carry a real delivered answer and a MiniMax-3 median score of record. Counts:

| failure_layer | cc | codex | agy | total | counts as real weakness? |
|---|---:|---:|---:|---:|---|
| `genuine_capability` | 3 | 5 | 28 | **36** | ✓ genuine model weakness |
| `task_design` (rubric grades undisclosed/forbidden/unstaged pipeline) | 2 | 3 | 3 | **8** | ✗ rubric/task defect |
| `partial_delivery` (deliverable file never written) | 0 | 0 | 1 | **1** | ✗ harness/deliverable gap |
| **TOTAL low-scoring cells** | **5** | **8** | **32** | **45** | — |

**Genuine vs defect split:** **36 / 45 (80%) are genuine model weaknesses**; **9 / 45 (20%) are rubric/task defects (8) or a partial-delivery gap (1)**. Per agent: cc **3 genuine / 2 defect**, codex **5 genuine / 3 defect**, agy **28 genuine / 4 non-weakness (3 task_design + 1 partial_delivery)**.

This is the key corrected result. v1 claimed ~37% of low scores were artifacts and that *all* cc/codex losses were artifacts; the canonical bundles show the opposite — only ~20% are defects, and cc/codex carry real genuine-capability losses (cc 3, codex 5).

---

## 4. Per-agent signatures

### 4.1 `cc` (Claude Opus 4.7) — 5 cells, 3 genuine / 2 task-design

Now fully present from `cc_bundle.json`. cc's losses concentrate on the correlated all-agent tasks. Its two **task-design** losses are over-specified rubrics, not science failures:
- **da-18-5 (mm3 0.44):** Answered the literal single-number ask correctly — MAPK frequency `90/762 = 11.81%` with full per-gene table (NF1 54/7.09%, KRAS 12), proper union logic, real DOIs/PMIDs (Razavi 2018 PMID 30205045). The rubric silently gates ~50/100 pts (C4/C5/C6) on an ESR1 mutual-exclusivity + naive-vs-post Fisher pipeline the question never asks for. **Defensible answer; rubric defect.**
- **da-26-2 (mm3 0.43):** Correct BH-FDR Pearson patient-vs-cell-line pipeline (TCGA 94,964 sig, CCLE 58 sig → 21,118 patient-specific pairs), honest A-prefix-only-matrix limitation. ~57 pts gated on an undisclosed Normality-LRT→t-skew→SSD pipeline + PTPN11. **Rubric defect.**

Its three **genuine_capability** losses are real method substitutions, all delivered:
- **da-20-4 (mm3 0.25):** Substituted DEG-set Jaccard / LFC-correlation + manual gene-panel inspection for the rubric's ranked Hallmark GSEA; computed **zero NES** for KRAS/EMT/MYOGENESIS; reached an *opposite* directional call on melanocytes (pigmentation-induction outlier vs the coordinated triple-suppression the GSEA would have shown). C3=0, C4=0, C5=0, C6=0.
- **da-24-3 (mm3 0.25):** Substituted positional locus-overlap + Pearson-of-z for the rubric's `coloc.abf` Bayesian colocalization; **wrongly claimed coloc needed an LD panel** (it doesn't — single-causal-variant ABF model) and skipped MAF/sdY/H0–H4 posteriors (~45 pts, C6/C7/C8).
- **da-6-2 (mm3 0.32):** Used coarse `any`-timepoint significance + k-means shape clustering instead of the all-4-timepoint completeness gate and 4-character Up/Down directional state-string encoding (C2/C3/C5, ~55 pts). The `.all()` it needed was trivially available — it chose `.any()`.

### 4.2 `codex` (gpt-5.5) — 8 cells, 5 genuine / 3 task-design

Real answers throughout. Its **task-design** losses (da-18-5 0.43, da-24-3 0.27, da-19-6 0.44) are the same over-specified rubrics:
- **da-19-6 (mm3 0.44):** Likely a *data-staging* defect — the rubric gates ~50 pts (C2+C3) on a BAM-coverage→CPM→log2FC pipeline, but only peak-level files (narrowPeak/xls/summits) were staged; codex correctly delivered the directional closing science (39,139 lost vs 13,231 gained intervals; 22.86% peak-count drop *not* explained by depth) and explicitly named the missing count-based step. (No verify verdict attached; first-pass confidence 0.68.)

Its five **genuine_capability** losses are real:
- **da-20-4 (mm3 0.10, lowest cell in the set):** Homemade Gaussian OLS/t-test on logCPM instead of count-based DESeq2+apeglm; **no ranked GSEA**, so zero Hallmark NES; eyeball ORA gene lists. C3/C4/C5/C6 all 0.
- **da-26-2 (mm3 0.35):** Spearman+BH-FDR substituted for the prescribed Normality-LRT→t-skew→SSD→druggable pipeline; no PTPN11 (hits were A2M/ABI3BP/AC-prefixed lncRNAs). *(Note: codex's da-26-2 was adjudicated genuine while cc's and agy's were task-design — see §5.)*
- **da-20-1 (0.41):** PCA+PERMANOVA+silhouette instead of TruncatedSVD→K-means(k=4)+cross-tab; 2,000 HVGs not ~10,000; never reported lineage markers (ACTA2/TAGLN, DCN/LUM, MEST/MDK).
- **da-25-1 (0.48):** Ran mutation–T-stage on `CLIN_T_STAGE` only; never used the more-complete `PATH_T_STAGE` it had already tabulated (~495 vs 406 usable), missing the canonical TP53 FDR-significant hit (OR=3.08, FDR=0.0379).
- **da-6-2 (0.42):** Same all-4-timepoint/4-state-string substitution as cc (any-timepoint + k-means + peak-timing).

### 4.3 `agy` (Gemini 3.1 Pro) — 32 cells, the dominant genuine signal (method-substitution workhorse)

**28 of 32** cells are `genuine_capability` (mm3 0.18–0.53, median 0.41), all delivered. agy's monotone failure mode: **run a real but coarser statistic and skip the rubric's highest-weight criterion.** Five concrete examples, each with the criterion lost and agy's actual numbers:

1. **da-13-6 (mm3 0.40) — single global correlation for per-protein concordance.** Reported one Spearman per regimen (`rho = -0.332` CPA-vs-menopause, `+0.291` CPA-vs-MHT) and filtered on the **wrong gene set** (proteins significant in Menopause/MHT, not GAHT-affected). **Lost C1+C3+C4 (60 pts):** the rubric wants GAHT-filtered per-protein direction-concordance counts (CPA 160 same/52 opp ≈75%; SPIRO 71 same/9 opp ≈89%) and named discordant proteins (CXCL13, NOS3). The rubric-correct values reproduce exactly from the raw CSVs — the rubric is well-posed; agy simply ran a different analysis.

2. **da-13-5 (mm3 0.30) — global Fisher for per-regimen hypergeometric.** Used a single combined `GAHT_effect==1` set (213 proteins, no SPIRO) and a Bonferroni-thresholded sex set (1,699 proteins, **not** top-100), then Fisher's exact (OR=3.39). Headlined "85.4% (182/213)" — the wrong fraction. **Lost C2+C3 (40 pts):** rubric wants per-regimen overlap vs **top-100** sex proteins via hypergeometric (gold: CPA K=245 overlap=36; SPIRO K=91 overlap=21), which reproduces exactly. SPIRO regimen essentially absent; directional concordance collapsed to 63.6% vs gold ~97–100%.

3. **da-15-2 (mm3 0.18) — case/control PCA-eigengene proxy for ALS-only WGCNA + skipped enrichment.** Ran on ALS+Control (N=138 vs 36) with `log2(TPM)`, unsigned power=6, producing 156 flat modules (~6.5× the expected ~24) and **never loaded the staged Mathys markers** — so the four-marker Fisher cell-type enrichment (**C4, 22 pts**) scored 0; it only eyeballed gene names (TREM2/TYROBP/APOE). Headline (Module 74, microglial, r=0.528, FDR=2.75e-13) is biologically right but earns little rubric weight.

4. **da-19-6 (mm3 0.25) — peak COUNTS for per-region coverage→log2FC.** Reported a 9.4% consensus-peak drop (41,201→37,337) but **never computed increased-vs-decreased REGION counts**; loaded `signalValue` then discarded it on a global mean. **Lost C2+C3 (50 pts).** (Partial task-design wrinkle: the rubric's named `bedtools multicov on filtered BAM` path is uncomputable since only narrowPeak/xls were staged — but the xls `pileup`/`fold_enrichment` gave a coverage proxy agy never attempted, so this is under-rigor, not a pure task defect.)

5. **da-6-2 (mm3 0.27) — cross-sex Pearson + mean/max-|logFC| heuristic for the 4-state pipeline.** Skipped FDR significance gating (loaded `training_q`, never used it), never built the per-sex 4-character Up/Down state string, never ranked 4-state patterns. **Lost C2+C3+C5 (55 pts).** Invented a "Discordant" bucket the rubric never asks for (81 genes). Verify confirmed genuine.

agy's only non-genuine cells: **3 task-design** (da-20-4 0.15, da-24-3 0.17, da-26-2 0.35 — all forbidden-paper/undisclosed-pipeline rubrics) and **1 partial_delivery** (da-6-5 0.14 — `/app/trace.md` never written; agy demonstrably did the correct computation — recomputed Jaccard 0.1957 matches its reported 0.196 — but never serialized methodology to the graded file).

---

## 5. Correlated all-agent tasks (da-18-5 / da-20-4 / da-24-3 / da-26-2 / da-6-2)

Per-agent verify verdicts (`low_score_is_genuine`) show these do **not** share a single cause:

| task | cc | codex | agy | corrected reading |
|---|---|---|---|---|
| **da-18-5** | task_design (0.44, **defect**) | task_design (0.43, **defect**) | genuine (0.34, **real**) | **Mostly rubric defect.** Rubric gates ~50–65 pts on an ESR1 mutual-exclusivity Fisher pipeline absent from the one-sentence question (ESR1 appears 0× in question, 8–12× in rubric) and derived from the *forbidden* source paper. cc/codex answered the literal frequency correctly. **agy is the exception — genuinely failed:** wrong MAPK gene set (omitted ERBB2/ERBB3/EGFR, added NRAS), headline `9.6% (73/762)` contradicting its own trace; gene-set error is a real defect against the source-faithful gene definition. |
| **da-20-4** | genuine (0.25, **real**) | genuine (0.10, **real**) | task_design (0.15, **defect**) | **Mixed.** cc and codex genuinely failed — both substituted overlap/correlation or OLS for ranked Hallmark GSEA and produced **zero NES**. agy's verdict is task_design: the rubric gates 65/100 on NES for three named pathways the plain question never mentions and whose target values are the *forbidden* paper's figure; agy gave a defensible correlation answer to the literal "consistent vs divergent" question (matching the gold's "melanocytes most distinct" headline). |
| **da-24-3** | genuine (0.25, **real**) | task_design (0.27, **defect**) | task_design (0.17, **defect**) | **Mostly rubric defect.** Rubric gates 60–80 pts on an undisclosed `coloc.abf` (H0–H4) + IV-meta pipeline; the open question only asks to "find shared genetic factors," the source paper is forbidden, and sample-size-weighted criteria are **ungradeable** (no N column in the 9-column schema). All three converged on threshold+clump+pleiotropy → the shared ACADM locus. cc's cell is graded genuine because cc *falsely claimed* coloc.abf needs an LD panel (it doesn't), making its skip a real capability error even though the gate itself is defective. |
| **da-26-2** | task_design (0.43, **defect**) | genuine (0.35, **real**) | task_design (0.35, **defect**) | **CONFIRMED RUBRIC DEFECT (forbidden-paper pipeline).** ~60–73/100 pts gate on an undisclosed Normality-LRT → Normal/T-skew classification → SSD ranking → druggable filter → the specific gene **PTPN11**. None of those terms appear in `instruction.md`, which *explicitly forbids reading the source paper* that defines them. A sound on-question correlation answer is structurally capped near 0.35. codex's cell is the one graded genuine (its Spearman pipeline was both off-rubric *and* under-rigorous with an underpowered n=35 CCLE arm), but the dominant signal for cc/agy is the defective rubric. |
| **da-6-2** | genuine (0.32, **real**) | genuine (0.42, **real**) | genuine (0.27, **real**) | **GENUINELY HARD FOR ALL THREE.** Every agent substituted a coarser pipeline (any-timepoint significance, k-means shape clustering, or cross-sex Pearson) for the rubric's all-4-timepoint completeness gate → 4-character Up/Down state-string encoding → ranked 4-state patterns. The rubric is a coherent, fully executable temporal-omics discretization; all three had the data and even the intermediates but ran a different, weaker analysis. This is a real shared capability gap, not a rubric artifact. |

**Net:** da-6-2 is genuine-hard (3/3); da-26-2 is a confirmed forbidden-paper rubric defect; da-24-3 and da-18-5 are predominantly rubric defects (with one genuine agent exception each); da-20-4 is mixed (2 genuine, 1 defect). No single systemic cause.

---

## 6. Rubric/task defects found (every `task_design` + `partial_delivery` cell)

Eight rubric defects and one deliverable gap, with the specific defect and fix:

1. **da-18-5 · cc (0.44) & codex (0.43) — un-asked ESR1 mutual-exclusivity gate.** The one-sentence question asks only for cumulative MAPK frequency; the rubric gates ~50–65 pts (C4/C5/C6/C7) on ESR1-stratified frequencies + a Fisher mutual-exclusivity test, the *headline finding of the forbidden source paper*. **Fix:** rewrite the question to request the ESR1/naive stratification explicitly, or reweight the rubric so the headline frequency the question actually asks for carries the majority of points.

2. **da-19-6 · codex (0.44) — BAM-coverage rubric on a peak-only stage.** C2[A]/C3[A] require `bedtools multicov on filtered BAM files`, but only narrowPeak/xls/summits were staged. **Fix:** stage the filtered BAM/bigWig files named in the manifest, or rebalance C2/C3 to accept peak-call consensus + binary loss/gain + fragment-normalized burden as level A when BAMs are absent.

3. **da-20-4 · agy (0.15) — hidden GSEA/NES key from a forbidden figure.** 65/100 pts gate on ranked-Hallmark NES for KRAS_SIGNALING_UP/EMT/MYOGENESIS, named nowhere in the plain question, with target NES values that are the forbidden paper's figure. **Fix:** disclose the GSEA target in the question, or reweight so a sound answer to the actual "consistent vs divergent" question can score well without reproducing the forbidden figure.

4. **da-24-3 · codex (0.27) & agy (0.17) — undisclosed coloc.abf + IV-meta gate + ungradeable N.** 60–80 pts gate on `coloc.abf` (H0–H4) and inverse-variance meta-Z the open question never requests and the source paper (which defines them) is forbidden; sample-size-weighted criteria (C3) are uncomputable since the staged schema has **no N column**. **Fix:** name the intended methods in the instruction, reweight to reward any valid replicated-pleiotropic-locus method, and stage a per-cohort N (or drop the sample-size-weighting requirement). Stop forbidding the one paper whose pipeline the rubric demands.

5. **da-26-2 · cc (0.43) & agy (0.35) — forbidden-paper LRT/SSD/PTPN11 pipeline.** ~60–73 pts gate on an undisclosed Normality-LRT → t-skew classification → SSD ranking → druggable filter → PTPN11; none of those terms appear in the instruction, which forbids reading the defining paper. PTPN11 is absent from the A-prefix-only TCGA expression matrix, making it ungettable under the literal interpretation. **Fix:** disclose the methodology in the instruction (and lift the paper prohibition for the pipeline definition), or rewrite the rubric to reward any statistically defensible patient-specific-biomarker analysis (with FDR + a power-matched cell-line arm) rather than gating 21 pts on one paper-specific gene.

6. **da-6-5 · agy (0.14) — `partial_delivery`, deliverable never written.** The methodology-graded criteria (C1–C6, incl. the two heaviest at 20 pts each) had nothing to score because `/app/trace.md` was never written; only a 10-line `answer.txt` was emitted, though the science was correct (recomputed Jaccard 0.1957 ≈ reported 0.196). **Fix:** enforce `trace.md` emission in the agent harness (post-hoc fail/retry if `/app/trace.md` is absent); optionally let methodology stated in `answer.txt` satisfy C1–C6.

**Common pattern across 1–5:** the rubric grades fidelity to a *specific, undisclosed pipeline* (often the source paper's, which the instruction forbids reading) rather than whether the open/under-specified question was answered correctly — so a competent, well-grounded on-question answer is structurally capped well below 0.5.

---

## 7. Recommendations

1. **Audit rubrics for question↔rubric alignment.** For every task where the rubric names a specific pipeline, gene, or statistic, verify those terms appear in `instruction.md`. Where the instruction *forbids reading the source paper* yet the rubric demands that paper's method/answer (da-18-5, da-20-4, da-24-3, da-26-2), either disclose the method in the question or reweight points onto the question as literally asked. Audit `da-26-2`, `da-24-3`, `da-20-4`, `da-18-5`, and `da-19-6` first.
2. **Verify staged data matches rubric A-level inputs.** Several rubrics name files/columns absent from the container (BAMs in da-19-6; a sample-size N column in da-24-3; the full TCGA expression matrix / PTPN11 in da-26-2). Either stage them or rewrite the criterion.
3. **Fix the agy method-planning gap (the dominant genuine signal).** agy's 28 genuine losses are almost all *method substitution* — running a coarser statistic and skipping the highest-weight criterion despite having the data and intermediates. A pre-execution planning step that (a) extracts the rubric-prescribed pipeline name and required deliverables, (b) checks the chosen method against them (e.g. "rubric says coloc.abf / DESeq2+apeglm / all-4-timepoint gate — am I running exactly that?"), and (c) enforces emission of every named deliverable (incl. `trace.md`, per da-6-5) would recover most of the lost criteria.
4. **Treat local `runs/harbor_base_matrix` copies as unreliable.** The partial local matrix copy had rate-limited replicates that masquerade as non-deliveries and caused v1's inversion. **Use `runs/cc_bundle.json` and `runs/codex_bundle.json` as the canonical answer source** for cc and codex; reserve the matrix for agy only (where the bundle is unavailable), and prefer the bundle wherever both exist.
5. **MiniMax-3 median is the score of record.** The complete 450/450 neutral rejudge is the single grading authority for all analyses going forward.

---

## 8. Caveats

- **Per-rep delivery: VERIFIED against the full 450 (`runs/cap3`).** The classification above read one representative rep per cell (bundle for cc/codex, matrix for agy). The canonical 3-rep run was staged in a private run archive, then inspected locally as `runs/cap3/`: 450/450 reps each with `answer.txt` + `trace.md`. That archive was used to decompose every failing median into its three replicate traces (`scripts/cap3_decompose.py`). Result: **44 / 45 failing cells delivered a real answer in all three reps**, so the low MiniMax-3 medians grade genuine work, not non-delivery floors — confirming this report over v1. Wide per-rep norms (e.g. agy/da-11-1 `[0.03, 0.24, 0.38]`, answers 269/319/132 B) are real run-to-run *quality* variance, not empty reps.
- **One true non-delivery: `agy/da-8-2`.** Its reps wrote `[7, 7, 502]` bytes — two 7-byte stubs and one real answer — so its 0.22 median is partly a non-delivery floor. **Reclassify da-8-2 from `genuine_capability` → `partial_delivery`** (joining da-6-5). Corrected non-weakness count: agy 5 (3 task_design + 2 partial_delivery); overall genuine 35 / 45 (78%), defect/gap 10 / 45 (22%).
- **agy is the least rep-consistent agent.** Its failing-cell norms swing widely (da-13-6 `[0.2,0.4,0.6]`, da-15-2 `[0.16,0.18,0.5]`, da-9-1 `[0.24,0.42,0.59]`) — a second-order weakness on top of method substitution: even when it picks a defensible approach, answer quality is unstable across reps. cc and codex norms are far tighter.
- **Source discipline.** Use `runs/cap3/` (canonical, 3 reps/task) for all future per-rep work; `runs/harbor_base_matrix` is a partial copy with rate-limited reps and must not be used; the `*_bundle.json` files are a convenience 1-rep/task extract. MiniMax-3 median remains the sole score of record.
- **Single judge of record.** All conclusions depend on MiniMax-3 median as the sole grader. There is no independent cross-judge corroboration in this report (by design — no other judge is admitted). Systematic MiniMax-3 calibration error, if any, would propagate uniformly; the per-cell verify verdicts mitigate this by independently re-deriving scores from the rubric and reproducing the agents' computations against the raw data, but they are still anchored to the MiniMax-3 number as the target.
