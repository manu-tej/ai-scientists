# BixBench-Verified-50: 3-agent capability + consistency results

**Date:** 2026-06-05
**Agents:** `claude-code` (cc, Claude Opus 4.7) · `codex` (gpt-5.5) · `antigravity-cli` (agy, Gemini 3.1 Pro)
**Protocol:** k=3 replicates per task; neutral judge = OpenRouter `minimax/minimax-m3` (third party to all three agents, no daily cap)
**Artifacts:** `results/bixbench/` (grade JSONs + summaries) · pipeline `scripts/bixbench/run_pipeline.sh`

## Headline

The 15-task *easy* subset (smallest capsules) **inverted** the true ranking. On the hard,
difficulty-representative tasks the order is **cc > agy > codex** — and it survives every
verifier correction (the fixes lift all three agents symmetrically).

| View | open-answer ranking |
|---|---|
| Easy-15 subset | codex 0.933 > agy 0.911 > cc 0.889 |
| MiniMax baseline (BiomniBench-DA) | cc 0.806 > codex 0.737 > agy 0.494 |
| **Hard-35 (BixBench)** | **cc 0.828 > agy 0.790 > codex 0.735** |
| **Full-50 (BixBench)** | **cc 0.847 > agy 0.827 > codex 0.796** |

### Full-50 (verifier-fixed)

| Agent | open | MCQ | consistency |
|---|---|---|---|
| **cc** | **0.847** | 0.927 | 0.979 |
| **agy** | 0.827 | 0.907 | **0.986** |
| **codex** | 0.796 | 0.927 | 0.972 |

## Three findings

1. **Difficulty calibration changes the ranking.** codex looked *best* on the easy subset
   (0.933) but is *worst* on the hard tasks (0.735) — a −0.28 cliff. cc and agy degrade
   gracefully. An uncalibrated benchmark can rank agents backwards.

2. **Capability ≠ consistency.** cc is the most capable (0.847) but agy is the most
   consistent run-to-run (0.986). "Best agent" depends on which axis you weight — the
   trust-vs-accuracy divergence this project is built to surface.

3. **"All-agents-fail" ≠ "agents are bad."** Of the 8 tasks all three initially failed,
   **2 were verifier bugs** (correct answers scored 0) and most of the rest are
   *correlated cross-agent failures* — the agents agree with each other on a defensible
   reading that differs from the answer key. Raw "accuracy" conflates real capability
   gaps with verifier brittleness and question ambiguity.

## Verifier bugs found and fixed (`scripts/grade_bixbench.py`)

Three brittleness bugs, each scoring **correct** answers as 0; all fixed symmetrically
(so the ranking is unchanged) and covered by `scripts/bixbench/test_verifiers.py`:

| Bug | Example | Task |
|---|---|---|
| thousands separator | `19159` ≠ `19,159` | bix-52-q7 |
| fraction-numerator grab | `30/41 (0.732)` read as `30` | bix-14-q1 |
| no scientific notation | `1.03E-07` unparseable | bix-52-q2 |

Fix: `range_verifier` parses sci-notation, splits the ideal `(lo,hi)` per-bound, and
accepts if **any** number in the answer falls in range; `str_verifier` strips
thousands-commas. The correction raised every agent ~+0.05 on the hard set.

## Audit of the 8 all-agents-fail tasks

| Task | mode | verdict |
|---|---|---|
| bix-14-q1 | range | ✅ verifier bug (fraction) → **fixed**, all correct |
| bix-52-q2 | range | ✅ verifier bug (sci-notation) → **fixed**, all correct |
| bix-54-q7 | range | 🔬 correlated failure — gold correct, agents drop the monoculture anchors (proven, `repro_bix54_q7.R`) |
| bix-16-q1 | str | 🔬 correlated — DepMap sign-convention ambiguity; agents `CCND1` (rank #1, codex's rho exact to 7 dp), gold `CDKN1A` is the exact mirror under the negated convention (proven, `repro_bix16_q1.py`) |
| bix-27-q5 | range | 🔬 correlated near-miss — all agents `56.47%` vs tight `(55,56)` |
| bix-45-q1 | llm | 🔬 correlated near-miss — all `1.52e-56` vs gold `7.7e-54` (both hugely significant) |
| bix-61-q5 | llm | 🔬 correlated near-miss — all `2.56` vs gold `2.68` Ts/Tv (variant-pipeline dependent) |
| bix-26-q5 | str | ⚠️ genuinely hard — agents *disagree* (cc=1, codex/agy=2), gold=3 |

Two reproductions confirmed the answer key is correct while the agents are *consistently*
(not randomly) wrong — the signature biology-agent failure mode, invisible to per-agent
consistency (all ~0.96–0.99) but caught by cross-agent agreement.

## Reproduce

See `scripts/bixbench/run_pipeline.sh` for the end-to-end recipe (HF bucket → build →
run → grade → merge) and `docs/research/2026-06-04-bixbench-verified-50-integration.md`
for the task-adapter design. The two task investigations:

```
Rscript scripts/bixbench/repro_bix54_q7.R scripts/bixbench/fixtures/Swarm_2.csv
python  scripts/bixbench/repro_bix16_q1.py --data <capsule CapsuleData dir>   # DepMap, ~1GB
python  scripts/bixbench/merge_grades.py --agent cc <subset> <full> ...        # rebuild summary
python  scripts/bixbench/test_verifiers.py                                     # verifier regressions
```

## Operational notes

- codex ran all 35 hard tasks with **zero quota stalls** (~3h); the ChatGPT daily-quota
  worry never materialized.
- cc and agy hit a rep-3 hang pattern on a few tasks; `bench/run.sh`'s 3600s agent
  timeout + retry self-healed each one. Host memory stayed healthy (~24G free of 30G)
  the whole ~5h; the co-located home-media stack was never touched.
- Efficiency: the 15 easy-subset tasks were already run, so only the 35 new tasks were
  built and executed (saved ~1/3 of the compute).
