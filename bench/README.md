# bench/ — the benchbench runner

Three composable tools that replace ~13 scattered scripts. A benchmark run is now a
**config**, not a new script. Same code on the Mac and on serene — only host-specific env
differs.

```
assemble.py   what to run   (dataset + prompt → buildable harbor tasks)
run.sh        how to run    (tasks × agents × replicates → collected traces)
grade.py      how to score  (traces → capability / refusal scores)
```

It runs everything on **$0 subscription auth** (codex ChatGPT OAuth, claude-code Max OAuth,
antigravity Google token, gemini OAuth). The agent never sees an API key; a verifier/judge
key reaches only the verifier (`--ve`) or the judge (`grade.py`).

---

## The pipeline

### 1. assemble — build the tasks

```bash
# base (answerable) tasks, with the refusal affordance, verifier kept for inline grading
uv run python bench/assemble.py --base --all --verified --out runs/harbor_base_tasks

# variant (unanswerable) tasks (perturbed data from runs/variants, scaffold from the base)
uv run python bench/assemble.py --variant --all --out runs/harbor_tasks
```

| flag | meaning | default |
|------|---------|---------|
| `--dataset DIR` | base-task source (scaffold + base data) | `data/biomnibench-da` |
| `--base` / `--variant` | base (answerable) or variant (unanswerable, data from `runs/variants`) | `--base` |
| `--prompt PATH\|none` | affordance/prompt template to append (byte-identical across base+variant) | built-in `REFUSAL_AFFORDANCE` |
| `--verified` | keep `verifier.env` (inline judge) vs strip it (collect-only) | strip |
| `--task ID` / `--all` | one task or all eligible (`validated_variants()` / `is_complete()`) | — |
| `--out DIR` | output task tree | `runs/harbor_tasks` |

Folds in Dockerfile generation + a **buildability preflight** that fails loudly if any task
lacks a build definition (the silent-gap bug, made loud). Data is hardlinked (zero extra disk).

### 2. run — execute the matrix

```bash
# baseline capability on the Mac: 3 agents over the base tasks, collect traces
bench/run.sh --dataset runs/harbor_base_tasks --agents "codex claude-code antigravity-cli" --out runs/cap

# a sole-arm codex push on serene with pacing + build-cache kept
BB_PRUNE_BUILDER=0 BB_PACE_SEC=5 BB_RETRIES=3 \
  bench/run.sh --dataset runs/harbor_tasks --agents codex --out runs/harbor_variant_matrix

# K replicates (builds each image ONCE, runs the agent K times)
bench/run.sh --dataset runs/harbor_tasks --agents codex --replicates 5 --out runs/rep5

# see the exact commands without running (secrets redacted)
BB_DRY_RUN=1 bench/run.sh --dataset runs/harbor_tasks --agents "codex claude-code" --replicates 2
```

| flag / env | meaning | default |
|------------|---------|---------|
| `--dataset DIR` (`BB_TASKS_DIR`) | task tree to run | `runs/harbor_tasks` |
| `--agents "a b"` (`BB_AGENTS`) | `codex` `claude-code` `antigravity-cli` `gemini-cli` | `codex` |
| `--replicates K` (`BB_REPLICATES`) | harbor `-n K` — build once, run K times | `1` |
| `--out DIR` (`BB_OUT`) | output root | `runs/harbor_matrix` |
| `--verify` | run BiomniBench's verifier (`--ve ANTHROPIC_API_KEY`) | collect-only |
| `BB_DRY_RUN=1` | print the command (secrets redacted), don't run | off |
| `BB_PACE_SEC` `BB_RETRIES` `BB_BACKOFF_SEC` `BB_BATCH` `BB_BATCH_COOLDOWN` `BB_INITIAL_COOLDOWN` | codex pacing / 429-resilience (all default off) | — |
| `BB_PRUNE_BUILDER` | builder-cache prune per task: `1` on the **Mac** (VM-disk), `0` on **serene** | `1` |

Resume-safe (skips cells already done — replicate-aware), concurrency-safe cleanup (multiple
agent arms can share one host). **One codex arm per ChatGPT subscription at a time** (concurrent
codex arms 429 each other; cc / agy are separate accounts and may run alongside).

### 3. grade — score the traces

```bash
# capability (Phylo rubric, Gemini 3.1 Pro)
uv run --env-file .env python bench/grade.py --mode capability --root runs/cap/codex --out runs/cap_codex.json

# refusal 2×2: appropriate-refusal on variants, false-refusal on base/control
uv run --env-file .env python bench/grade.py --mode refusal --submode variant --root runs/harbor_variant_matrix/codex --out runs/ref_codex.json

# N-vote majority + inter-vote agreement (keeps the default Phylo-faithful judge settings)
uv run --env-file .env python bench/grade.py --mode capability --root runs/cap/codex --votes 3 --out runs/cap_codex_v3.json
```

| flag | meaning | default |
|------|---------|---------|
| `--mode capability\|refusal` | rubric scoring vs 4-way behavior classification | — |
| `--submode control\|variant` | (refusal) answerable→false-refusal vs unanswerable→appropriate-refusal | inferred |
| `--model ID` | `gemini-*` (API), `claude-*` (API), `claude-cli:*`, `gemini-cli:*` | `gemini-3.1-pro-preview` |
| `--votes N` | N judge calls → majority + agreement (N=1 = single, default settings) | `1` |
| `--root DIR` / `--out JSON` | harbor run dir to score / output | — |

Reads whichever trace surface a cell has — `artifacts/trace.md` if present, else recovers from
`agent/<harness>.txt` — so reused and fresh cells grade uniformly.

---

## Mac vs serene

Identical commands; only the host env differs:

| | Mac | serene |
|---|---|---|
| `BB_PRUNE_BUILDER` | `1` (fixed Docker-VM disk) | `0` (native Docker, keep base layer) |
| repo path | `~/2026/ai-scientists` | `~/benchbench` |
| codex pacing | optional | optional (sole-arm sustained push) |

---

## Notes

- **Capability numbers depend on the trace surface.** The original `*_rejudge_*.json` references
  were scored from pre-baked `*_bundle.json` files whose traces were fuller than the on-disk
  `agent/codex.txt` for some base cells; re-grading from disk can score those lower. New runs
  write full `artifacts/trace.md`, so there is no bundle/disk gap going forward.
- The legacy `scripts/run_*_matrix.sh`, `scripts/harbor_migrate*.py`, `scripts/*grade*/judge*`
  remain until the in-flight experiment finishes; `bench/` reproduces them byte-for-byte
  (verified) and is the path forward.
- `grade.py` imports `harbor_trace_extract` from `scripts/`; that helper moves into `bench/`
  when the legacy scripts are retired.
