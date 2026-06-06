# BixBench-Verified-50: 3-agent capability + consistency results

**Date:** 2026-06-05
**Agents:** `claude-code` (cc, Claude Opus 4.7) · `codex` (gpt-5.5) · `antigravity-cli` (agy, Gemini 3.1 Pro)
**Protocol:** k=3 replicates per task; neutral judge = OpenRouter `minimax/minimax-m3` (third party to all three agents, no daily cap)
**Artifacts:** `results/bixbench/` (grade JSONs + summaries) · pipeline `scripts/bixbench/run_pipeline.sh`

## Headline

On a hard, real biology benchmark, **the trust axis separates from the accuracy axis**, and
raw accuracy *understates* the agents for two measurable reasons (verifier brittleness and
question ambiguity). "Best agent" depends on whether you weight capability or reliability.

| Axis | Ranking (full-50, open-answer) |
|---|---|
| **Capability** | **cc 0.847 > agy 0.827 > codex 0.796** |
| **Consistency** (run-to-run agreement) | **agy 0.986 > cc 0.979 > codex 0.972** |

| Agent | open | MCQ | consistency |
|---|---|---|---|
| **cc** | **0.847** | 0.927 | 0.979 |
| **agy** | 0.827 | 0.907 | **0.986** |
| **codex** | 0.796 | 0.927 | 0.972 |

(Hard-35-only, the difficulty-representative tasks: cc 0.828 > agy 0.790 > codex 0.735.)

## The two findings that matter

### 1. Capability ≠ consistency

cc is the most *capable* (0.847) but agy is the most *consistent* run-to-run (0.986). The
accuracy ranking and the reliability ranking disagree — exactly the trust-vs-capability
divergence this project exists to measure. An accuracy-only leaderboard would call cc the
winner and never surface that agy is the steadier agent.

### 2. When agents fail, they fail *together* — and the verifier mislabels some of it

Of the 8 tasks all three agents initially "failed":
- **2 were verifier bugs** — correct answers scored 0 by a brittle numeric grader.
- **5 were correlated cross-agent failures** — the agents agree *with each other* on a
  defensible reading that the answer key rejects (not random error).
- **1 was genuinely hard** (the only task where the agents even disagree among themselves).

This is the more novel point: **the failure mode of frontier biology agents is shared
systematic bias, not noise.** Per-agent consistency (all ~0.96–0.99) is blind to it — every
agent is individually self-consistent while being collectively, confidently wrong. Only a
*cross-agent* agreement signal catches it. An accuracy benchmark scores it as a flat
"0, hard task" and learns nothing.

Two cases proven by reproduction (scripts in `scripts/bixbench/`):
- **bix-54-q7** — the gold range is *correct*; all three agents drop the monoculture anchors
  from the proportion–response curve, landing ~2% low (`repro_bix54_q7.R`).
- **bix-16-q1** — a DepMap sign-convention ambiguity; the agents' `CCND1` is the literal
  rank-#1 answer (codex's rho matches to 7 decimals) and the gold `CDKN1A` is its exact
  mirror under the negated convention (`repro_bix16_q1.py`). Neither is "wrong."

## Verifier bugs found and fixed (`scripts/grade_bixbench.py`)

Three brittleness bugs, each scoring **correct** answers as 0; all fixed symmetrically (so
the ranking is unchanged) and locked by `scripts/bixbench/test_verifiers.py`:

| Bug | Example | Task |
|---|---|---|
| thousands separator | `19159` ≠ `19,159` | bix-52-q7 |
| fraction-numerator grab | `30/41 (0.732)` read as `30` | bix-14-q1 |
| no scientific notation | `1.03E-07` unparseable | bix-52-q2 |

Fix: `range_verifier` parses sci-notation, splits the ideal `(lo,hi)` per-bound, and accepts
if **any** number in the answer falls in range; `str_verifier` strips thousands-commas. The
correction raised every agent ~+0.05 on the hard set — the takeaway being that automated
numeric verifiers are a systematic false-negative source worth auditing before trusting any
absolute number.

## Audit of the 8 all-agents-fail tasks

| Task | mode | verdict |
|---|---|---|
| bix-14-q1 | range | ✅ verifier bug (fraction) → **fixed**, all correct |
| bix-52-q2 | range | ✅ verifier bug (sci-notation) → **fixed**, all correct |
| bix-54-q7 | range | 🔬 correlated failure — gold correct, agents drop the monoculture anchors (proven) |
| bix-16-q1 | str | 🔬 correlated — DepMap sign-convention ambiguity; neither side "wrong" (proven) |
| bix-27-q5 | range | 🔬 correlated near-miss — all agents `56.47%` vs tight `(55,56)` |
| bix-45-q1 | llm | 🔬 correlated near-miss — all `1.52e-56` vs gold `7.7e-54` (both hugely significant) |
| bix-61-q5 | llm | 🔬 correlated near-miss — all `2.56` vs gold `2.68` Ts/Tv (variant-pipeline dependent) |
| bix-26-q5 | str | ⚠️ genuinely hard — agents *disagree* (cc=1, codex/agy=2), gold=3 |

## Reproduce

End-to-end recipe in `scripts/bixbench/run_pipeline.sh` (HF bucket → build → run → grade →
merge); task-adapter design in `docs/research/2026-06-04-bixbench-verified-50-integration.md`.

```
Rscript scripts/bixbench/repro_bix54_q7.R scripts/bixbench/fixtures/Swarm_2.csv
python  scripts/bixbench/repro_bix16_q1.py --data <capsule CapsuleData dir>   # DepMap, ~1GB
python  scripts/bixbench/merge_grades.py --agent cc <subset> <full> ...        # rebuild summary
python  scripts/bixbench/test_verifiers.py                                     # verifier regressions
```

## Operational notes

- codex ran all 35 hard tasks with **zero quota stalls** (~3h); the ChatGPT daily-quota
  worry never materialized.
- cc and agy hit a rep-3 hang pattern on a few tasks; `bench/run.sh`'s 3600s agent timeout +
  retry self-healed each. Host memory stayed healthy (~24G free of 30G) the whole ~5h; the
  co-located home-media stack was never touched.

## Methodological note (not the main result)

We first graded a 15-task *easy* subset (the smallest capsules, already run) before the 35
hard tasks. The easy subset produced a *different* ranking (codex 0.933 > agy 0.911 > cc
0.889) — it lacked the difficulty to separate the agents and scored 11/15 tasks perfect for
everyone. It's a useful caution (don't rank agents on an uncalibrated subset), but it is not
the contribution; the hard/full-50 numbers above are the result.
