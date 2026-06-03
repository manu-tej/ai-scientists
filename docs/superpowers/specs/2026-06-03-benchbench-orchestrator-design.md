# benchbench orchestrator — design spec

**Date:** 2026-06-03
**Status:** Approved design, pre-implementation
**Author:** brainstormed with Claude (benchbench session)

## 1. Context

benchbench runs the Harbor framework to execute coding agents (codex, claude-code,
antigravity) in Docker sandboxes over BiomniBench-DA biomedical tasks, then grades the
results with an LLM judge. The scientific goal is a reliability/trust benchmark: does the
**refusal ranking** of frontier agents diverge from their **capability ranking**?

The current implementation works but has accreted into three loosely-coupled layers, each
with the same concepts re-implemented several times. A session of hard debugging exposed
the cost of that duplication: every fix had to be reasoned about per-script.

### Friction inventory (what this design replaces)

- **Orchestration** — three runner scripts (`run_base_matrix.sh`, `scripts/run_harbor_matrix.sh`,
  `scripts/run_variant_matrix.sh`) with near-identical agent-dispatch blocks copy-pasted
  three times, inconsistent auth sourcing (`.env` vs `~/.bb_cc_token` vs hardcoded), and the
  good logic (skip-guard, pacing, docker cleanup) present in only one of the three.
- **Task assembly** — `harbor_migrate.py` / `harbor_migrate_base.py` / `build_base_aff.py`
  with `migrate_toml()` and `assemble()` copy-pasted (differ only by `verified=True/False`),
  plus `gen_default_dockerfile.py`. The HF dataset ships no Dockerfiles; a pipeline generates
  them, and it silently skipped 8 base tasks — a class of bug with no preflight to catch it.
- **Grading** — 6+ standalone judge scripts sharing logic through `importlib` file-loading
  hacks, run as a manual step hours after the agent, each writing its own ad-hoc JSON with no
  index back to the runs.
- **Compute** — single-machine (mac/serene) with an 18GB "COPY data into image" build model
  that the replicate phase would multiply ~15×; operational babysitting over a flaky LAN ssh.

### Hard-won lessons this design must encode

1. **Per-credential serialization.** Two codex arms on one ChatGPT subscription rate-limit
   each other (403→429, corrupted traces) — *regardless of which machine they run on*.
   Serialization is a property of the credential, not the host.
2. **Buildability is not guaranteed.** Tasks can lack a Dockerfile silently; this must be a
   loud preflight failure.
3. **Hard failures must not masquerade as rate-limits.** A non-429 build failure that triggers
   a 20-minute "rate-limit" backoff wastes hours.
4. **Reuse must be quality-aware.** Cells are reusable only if genuinely clean (real answer +
   no tainting feature involved, e.g. codex imagegen).
5. **Heavy builds belong off the single machine.** Bind-mounted data (Modal Volume / HF)
   eliminates the per-task COPY entirely.

## 2. Goals & non-goals

### Goals
- One Python orchestrator replacing the bash runners, with a **pluggable compute backend**
  (`Executor`) so host / Modal / future AWS are swappable — *the AWS seam*.
- A **pluggable data backend** (`DataStore`) with **Hugging Face as the canonical, versioned,
  Xet-deduped source of truth**; serene-local and Modal-Volume are caches hydrated from HF.
- **Hybrid-by-weight routing**: light tasks on serene ($0), heavy tasks burst to Modal
  (~$0.10/task, $500 credits available).
- **Unified task assembly** (one parametric pipeline) and **unified grading** (capability +
  refusal, model-agnostic), with grading wired into the run, not a manual afterthought.
- **Reproducible variants**: specs + materialize code = a regenerable recipe; the materialized
  variant dataset = a published artifact whose provenance (base revision + spec hash + code
  version) is recorded and hash-asserted.
- A single **run-state store** (sqlite) for resume, skip, progress, and observability —
  replacing scattered `/tmp` logs and bash skip-guards.

### Non-goals
- Not replacing Harbor itself (it remains the host sandbox runtime).
- Not building the AWS backend now — only leaving the seam (a new `Executor` file later).
- Not publishing the variant dataset publicly yet (private until the Phylo licensing/collab
  conversation resolves).

## 3. Architecture

A new `bench/` package. Two orthogonal abstractions — compute and data — plus a thin spine.

```
RunConfig (declarative: matrix × backends × routing × data × grading)
      │
      ▼
  Scheduler ─────────── RunStore (sqlite: per-cell status, resume, progress, scores)
      │  owns the per-credential concurrency lock (codex→1, cc→1, agy→1) across ALL backends
      │
      ├─ builds CellSpec(task, agent, replicate, arm, weight, data_rev)
      │
      ├─ DataStore.fetch(task, rev) ─► resolve+cache task data (HF → local/Volume)
      │     ├─ HFDataStore        canonical, versioned, Xet-deduped   ← source of truth
      │     ├─ LocalDirStore      serene disk (cache)
      │     ├─ ModalVolumeStore   hydrated from HF (cache)
      │     └─ (future) S3Store    AWS, hydrated from HF
      │
      ├─ Router.route(cell) ─► picks an Executor by policy (weight → host vs Modal)
      │
      ├─ Executor.run(cell, data) -> CellResult    ← the AWS seam
      │     ├─ HostExecutor(target=serene)   native Docker, $0, light tasks
      │     ├─ HostExecutor(target=mac)      secondary
      │     ├─ ModalExecutor                 Volume bind-mount, heavy/burst
      │     └─ (future) AwsExecutor          new file, not a refactor
      │
      └─ Grader.score(result) -> CellScore   ← unified capability + refusal, model-agnostic
```

**Process placement.** The orchestrator runs *on serene* (always-on, native Docker, 546G):
host cells execute against local Docker, Modal cells dispatch to Modal's API over the
network. This removes the mac→serene ssh-babysitting entirely; the mac is a thin
control/monitor client.

## 4. Interfaces

```python
@dataclass(frozen=True)
class CellSpec:                 # the backend-agnostic unit of work
    task_id: str               # e.g. da-12-4_drop_survival
    agent: str                 # codex | claude-code | antigravity
    replicate: int             # 0..K-1
    arm: str                   # refusal | control | capability
    weight: str                # light | heavy   → drives routing
    data_rev: str              # pinned HF revision + spec hash → provenance

@dataclass
class CellResult:
    cell: CellSpec
    status: str                # ok | failed | refused | incomplete
    answer: str | None
    trace: str | None
    backend: str               # serene | modal | mac
    raw_dir: str               # full run output location
    returncode: int
    elapsed_sec: float
    err: str | None

@dataclass
class CellScore:
    cell: CellSpec
    kind: str                  # capability | refusal
    payload: dict              # capability: {score,max,normalized}; refusal: {classification,...}
    judge_model: str

class DataStore(Protocol):     # WHERE task data comes from
    def fetch(self, task_id: str, rev: str) -> Path: ...    # resolve+cache → local path
    def ensure(self, task_ids: list[str], rev: str) -> None: ...  # bulk hydrate

class Executor(Protocol):      # WHERE a cell runs  (the AWS seam)
    name: str
    def preflight(self, agents: set[str]) -> None: ...      # auth + buildability gates
    def run(self, cell: CellSpec, data_path: Path) -> CellResult: ...

class Grader(Protocol):        # HOW a result becomes a score
    def score(self, result: CellResult) -> CellScore: ...   # capability OR refusal
```

`Router.route(cell) -> Executor` is pure policy (`weight=="heavy" → Modal, else → serene`).
The **Scheduler** owns the per-credential concurrency lock so a codex cell on serene and one
on Modal can never run concurrently (the 403/429 invariant, made structurally impossible).

## 5. Data flow — three commands, one store

```
1.  bench build-variants     specs + base@HF → materialize → push artifact@HF (private)
                             records base_rev + spec_hash + code_ver; re-gen hash must match

2.  bench run <config>       RunStore ← Scheduler:
                               preflight(auth + buildability) → fail fast
                               for each pending cell:
                                 DataStore.fetch → Router.route → Executor.run
                                 → Grader.score → RunStore.put
                               resumable (skips cells already 'ok'); per-credential serialized

3.  bench report             aggregate RunStore → 2×2 (appropriate vs false refusal)
                             + capability table + Rabanser consistency across replicates
```

### RunConfig (declarative)

```yaml
matrix:
  arms:       [refusal, control, capability]
  agents:     [codex, claude-code, antigravity]
  replicates: 5
routing:
  heavy_to:    modal
  default_to:  serene
data:
  store:    hf
  repo:     <user>/trustbench-bio-variants   # private
  revision: <pinned>
grading:
  capability: {model: gemini-3.1-pro}
  refusal:    {model: gemini-3.1-pro}
```

## 6. Reproducible variants — recipe + artifact (both on HF, layered)

- **Recipe (source of truth):** perturbation specs (small YAMLs) + `materialize_variant.py` +
  a pinned *base* HF revision. Byte-deterministic: same spec + same base → identical bytes.
- **Artifact (published cache):** the materialized variants as a private HF dataset, Xet-backed
  (chunk-level dedup ≈ the local hardlinking — shared base chunks stored once). Provenance
  metadata baked in.
- **`build-variants` workflow:** regenerates the artifact from the recipe and asserts the
  hashes match the recorded provenance. This is the "reproducible workflow that creates the
  variants."

**Why HF helps access, concretely:** cloud backends (Modal, future AWS) pull cloud-to-cloud
from HF and cache locally — eliminating the ~3.7h home-network upload to a Modal Volume; every
backend reads the same pinned revision; the access layer and the eventual published artifact
are the same dataset.

**License note:** variants derive from Phylo's BiomniBench data. Keep the HF dataset **private**
during development; decide public release after the Phylo licensing/collaboration conversation.

## 7. Error handling

**Preflight gates** (once, before any compute):
- Buildability — every task has a Dockerfile/`docker_image` (catches the silent-gap bug).
- Auth — each agent credential resolves on each target backend (host env / Modal Secret).
- Data — HF revision resolves; required tasks present.

**Runtime** — each failure has one defined behavior:
- `429/403` → credential-scoped backoff + bounded retry (pauses only that lane).
- Hard build failure (non-429) → mark `failed`, surface immediately; never the rate-limit backoff.
- Timeout/hang → kill, mark `incomplete`, retry once.
- Empty/partial answer → Grader classifies `incomplete`; not a crash.
- Crash/resume → RunStore is the journal; rerun resumes from last `ok` cell.
- Idempotency — each attempt writes a fresh `raw_dir`; RunStore records the canonical one.

**Observability** — `bench status` reads RunStore (counts by status, per-credential lane
state), replacing ssh+grep across `/tmp`.

## 8. Testing

- **Golden (critical):** unified `Grader` reproduces current numbers (cc 0.747 / codex 0.675 /
  agy 0.462) on already-graded cells — proves consolidation changed no science.
- **Determinism:** `build-variants` twice → identical hashes.
- **Property:** credential lock — never two same-credential cells concurrent.
- **Integration:** the ~$0.10 Modal smoke test is the `ModalExecutor` integration test.
- **Unit:** Router policy, RunStore resume/skip, Grader trace-parsing on fixtures, assembly
  hash-determinism.

## 9. Build sequence (thin spine first, non-disruptive)

**Phase 0 — Spine + host, $0, zero disruption.** Build `bench/` alongside the running script:
the five interfaces, `RunStore`, `HostExecutor(serene)` wrapping the proven `run_variant_matrix`
logic, unified `assembly.py` (merges the 3 migrators + dockerfile-gen with a buildability
preflight), unified `grading.py` (merges the 6 graders). Validate against already-collected
data via golden tests. The in-flight run finishes on the old script; a one-time `bench import`
ingests `runs/harbor_*_matrix/` into RunStore so nothing re-runs.

**Phase 1 — Modal + HF, cheap validation.** `build-variants` → push current variants to private
HF, pin revision; `HFDataStore` + `ModalVolumeStore` hydrate from it; finish `ModalExecutor`'s
cc/agy CLI-flag TODOs; smoke-test one cell (~$0.10) — isolating the agy-under-gVisor risk to a
dollar, not a day. Router weight threshold goes live.

**Phase 2 — Replicate scale.** `RunConfig` with `replicates=K`, hybrid routing live, `bench
report` emits the 2×2 + capability + Rabanser consistency metrics across replicates.

Old scripts stay until `bench/` matches them on goldens, then are deleted.

**Risk ordering:** Phase 0 is pure refactor of proven logic validated against existing data
($0, cannot break the science); Phase 1 quarantines every unvalidated assumption (Modal, HF,
gVisor, agy-headless) behind a cheap smoke test; only Phase 2 spends real credits, by which
point every component has been exercised.

## 10. Open questions / risks

- **agy under Modal gVisor** — the antigravity CLI's headless run + token injection under
  gVisor is unproven; Phase 1 smoke test is the gate.
- **claude-code / agy CLI invocation flags** on Modal (instruction file + workdir) are TODOs in
  `modal_v2/app.py`.
- **HF Xet bucket specifics** — confirm exact `hf` CLI / API for the private dataset upload and
  Modal-side pull at implementation time (use the hf-cli skill / context7).
- **Scientific-Python pinning** — the Modal image must pin deps that were implicit on host
  (apt python3 + agent self-install); derive the set from representative `instruction.md`/`tests/`.
- **Phylo licensing** — gates public release of the variant dataset.

## 11. Component → file map (target)

```
bench/
  __init__.py
  spec.py          # CellSpec, CellResult, CellScore
  config.py        # RunConfig loader (yaml)
  store.py         # RunStore (sqlite): status, resume, scores, import
  scheduler.py     # matrix build, per-credential lock, retry/pace, drive loop
  router.py        # weight-based routing policy
  assembly.py      # unified task assembly (migrate + base + aff + dockerfile-gen + preflight)
  grading.py       # unified Grader (capability + refusal, model-agnostic)
  auth.py          # per-agent credential resolver (host env / Modal Secret)
  datastores/
    base.py        # DataStore protocol
    hf.py          # HFDataStore (canonical)
    local.py       # LocalDirStore (serene cache)
    modal_vol.py   # ModalVolumeStore (cache)
  executors/
    base.py        # Executor protocol + shared run scaffolding
    host.py        # HostExecutor(target=serene|mac) — wraps harbor run
    modal.py       # ModalExecutor — wraps modal_v2 app
  cli.py           # bench build-variants | run | report | status | import
```

Absorbs and then retires: `run_base_matrix.sh`, `scripts/run_harbor_matrix.sh`,
`scripts/run_variant_matrix.sh`, `scripts/harbor_migrate.py`, `scripts/harbor_migrate_base.py`,
`scripts/build_base_aff.py`, `scripts/gen_default_dockerfile.py`, and the 6 grader scripts.
