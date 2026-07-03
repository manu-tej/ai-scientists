# BixBench-Verified-50 → reliability pipeline (design)

**Date:** 2026-06-04
**Goal:** Generalization — run the agy reliability eval (capability + 3-rep consistency) on a
**second** benchmark (BixBench-Verified-50) to test whether the trust-ranking pattern we see on
BiomniBench-DA replicates off one benchmark. Source: HF bucket `amanutej/benchbench` →
`BixBench-Verified-50/` (synced to a private run worker for the run; capsules are ~3.5 GB).

**Decisions (user, 2026-06-04):** agent = **antigravity-cli (agy)** first; **smoke-test a few tasks**
before the full set; grading = **both** open-answer AND MCQ.

## Data format (from the JSONL index, 50 records)

Each record: `question`, `ideal` (gold), `distractors` (exactly 3 → MCQ), `answer` (bool),
`hypothesis`, `eval_mode`, `capsule_uuid`/`data_folder`, `short_id`/`question_id` (e.g. `bix-18-q3`),
`categories`, `canary` (contamination guard — never shown to agent).

- **50 questions over 33 capsules** (13 capsules carry multiple questions).
- **eval_mode**: `llm_verifier` (20), `str_verifier` (17), `range_verifier` (13) →
  **30/50 are code-graded**, only 20 need the Gemini judge (cheaper + more objective than BiomniBench's all-LLM rubric).
- **Capsule zip** contains `CapsuleData-<uuid>/` (raw data) **and** `CapsuleNotebook-<uuid>/..._executed.ipynb`
  (the worked solution). **The notebook MUST be stripped** — else the agent reads the answer.

## Harbor task contract (mirrors BiomniBench, verified on a private run worker)

```
<question_id>/
  task.toml                       # schema 1.3; artifacts answer.txt+trace.md; [task]/[metadata]/[verifier]/[agent]/[environment]
  instruction.md                  # <!-- TASK_ID --> + Question + Data Files + Required Outputs
  environment/Dockerfile          # FROM ubuntu:24.04 + python3/R + COPY data/ /app/data/ + WORKDIR /app
  environment/data/               # CapsuleData/* ONLY (notebook stripped)
  tests/grading.json              # {question, ideal, distractors, eval_mode, answer, hypothesis} for post-hoc grader
```
Runs through the **existing `bench/run.sh`** with no harness change (discovery needs task.toml +
environment/data + Dockerfile; `--disable-verification` skips in-Harbor verify; grading is separate).

## Component 1 — adapter `scripts/build_bixbench_tasks.py`
JSONL record + capsule zip → the task dir above. Strips `CapsuleNotebook/`, copies `CapsuleData/*`
to `environment/data/`, writes instruction/task.toml/grading.json. `--ids` selects a smoke subset.

## Component 2 — grader `scripts/grade_bixbench.py` (both modes)
Reads `tests/grading.json` + the agent's `answer.txt`. Two scores per (task, rep):
- **open-answer** per `eval_mode`:
  - `str_verifier` → normalized exact match to `ideal`.
  - `range_verifier` → parse `ideal` `(lo,hi)`; agent's numeric answer ∈ [lo,hi].
  - `llm_verifier` → Gemini judge: "is the answer equivalent to ideal?" → yes/no.
- **MCQ** → present `ideal`+3 `distractors` (shuffled); did the agent pick the option matching `ideal`?
Reuses the Gemini backend (bench/grade.py) for the 20 llm_verifier items; str/range are pure code.

## Component 3 — metrics (binary outcomes → richer consistency than rubric scores)
- **Capability** = mean accuracy over questions (majority-of-3 per question), open and MCQ separately.
- **Consistency** (the point of replicates):
  - *outcome consistency* — do all 3 reps land the same correct/wrong verdict?
  - *answer consistency* — do the 3 reps give the **same answer** (consistently wrong vs flipping)? = Rabanser outcome-consistency.

## Smoke set (one per verifier, small capsules)
| question_id | eval_mode | ideal | capsule (size) |
|---|---|---|---|
| bix-18-q3 | range_verifier | (69,72) | d59734d2 (22 KB) |
| bix-30-q3 | str_verifier | 0:0 | 3d4eb7bb (53 KB) |
| bix-53-q2 | llm_verifier | "Increases the number of diff…" | 308d53bf (600 KB) |

## Run plan
1. `hf buckets sync` the 3 smoke capsules + jsonl to the private run worker (native CLI, trusted).
2. `build_bixbench_tasks.py --ids bix-18-q3 bix-30-q3 bix-53-q2` → `runs/bixbench_smoke/`.
3. `bench/run.sh --agents antigravity-cli -k1 -n1 --max-effort` (1 rep, serialized — low load alongside cc/codex backfills).
4. `grade_bixbench.py` both modes → eyeball: did the adapter+verifiers work end-to-end?
5. If green → scale to 50 × 3 reps × agy (then cc/codex) for the generalization result.

## Open risks
- Capsule data may need bioinformatics packages the base image lacks — agent installs at runtime (BixBench's intended model); watch agent-timeout on heavy installs.
- `range_verifier` ideal strings vary in format (`(69,72)`, `(-0.064,-0.084) `, trailing spaces) — parser must be tolerant.
- Some `ideal` for `llm_verifier` are long prose — judge prompt must compare semantically, not literally.
