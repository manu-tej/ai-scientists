# Modal v2 execution harness — design

Status: DESIGN + PROTOTYPE only. **Nothing here has been run. No Modal compute spent.**
Target: run the BiomniBench-DA refusal matrix (3 subscription agents × ~109 variant
tasks + ~50 base tasks) on Modal, with the dataset **bind-mounted from a Volume**
instead of COPY'd into an 18 GB image per task.

---

## 0. What we are porting (from the local harness)

| Piece | Local (v1) reality | Source |
|---|---|---|
| Task assembly | `harbor_migrate.py` builds `runs/harbor_tasks/<task>/` = `instruction.md` + `tests/` + `environment/Dockerfile` + `environment/data/` (data **hardlinked** from base/variant tree). | `scripts/harbor_migrate.py` |
| Data weight | **83.1 GB unique** across all tasks (deduped by inode); 50 distinct base datasets; the largest single task data dir is **18 GB**. v1 `COPY data/... /app/data/` bakes that into every image. | `du` by inode |
| Agent: codex | Harbor `Codex` uploads `~/.codex/auth.json` into the sandbox, symlinks it to `$CODEX_HOME/auth.json`; run with `CODEX_FORCE_AUTH_JSON=1`, `-u OPENAI_API_KEY`. Our subclass `CodexNoImagegen` adds `-c features.image_generation=false`. | `codex_no_imagegen.py`, Harbor `codex.py:674` |
| Agent: claude-code | Subscription via env `CLAUDE_CODE_OAUTH_TOKEN`; strip `ANTHROPIC_API_KEY` so `apiKeySource=none` (else it bills the API). | `claude_code.py:1136`, `run_base_matrix.sh` |
| Agent: antigravity (agy) | No host file — agy stores its token in a Go keyring. We captured the **native-Linux token store** once into `runs/harbor_auth/agy_token_store.tgz`; `AntigravityCliOAuth` extracts `antigravity-oauth-token` + `installation_id` into `~/.gemini/antigravity-cli/` and writes `settings.json` (model display name, trusted workspaces). | `antigravity_oauth.py` |
| Deliverables | Agent writes `/app/answer.txt` + `/app/trace.md`; Harbor captures them as artifacts. Verification is **disabled** (`--disable-verification`); we judge traces later with our own judges. | `task.toml` artifacts block, `run_*_matrix.sh` |
| The affordance | Every instruction (base + variant, identical text) gets `REFUSAL_AFFORDANCE` appended — a sanctioned "INSUFFICIENT DATA" refusal path. This is the measurement substrate. | `harbor_migrate.py:35` |
| Rate-limit constraint | **Only ONE arm per subscription may run at a time.** Concurrent codex arms 429 each other and corrupt traces; same logic per Claude/Google account. Concurrency is *across the 3 accounts*, not within one. | `run_variant_matrix.sh` header |

---

## 1. The architectural question: Harbor-on-Modal (DinD) vs. agent-direct

Harbor runs each agent inside a **Docker sandbox** it builds and spawns. Modal functions
*also* run inside containers. So there are two ways to land on Modal:

### Option A — Harbor-on-Modal with docker-in-docker (DinD)
Run `harbor run ...` inside a Modal container that itself runs a Docker daemon, so Harbor
builds/spawns its inner sandbox exactly as it does on the Mac.

- Modal **does** support this: `Sandbox.create(..., experimental_options={"enable_docker": True})`
  (the `modal.com/docs/guide/docker-in-sandboxes` recipe). It requires the **2025.06 image
  builder**, a hand-rolled `start-dockerd.sh` (iptables-legacy SNAT, modern `runc`, gVisor
  caveats), and runs the inner container under gVisor with networking workarounds.
- **This is the wrong layer for our v2 goal.** v2 is specifically about *killing the
  18 GB-per-task image build*. If Harbor still owns the inner Docker, Harbor still does its
  `COPY data/... /app/data` (or we'd have to teach Harbor's environment layer to bind-mount,
  which is a Harbor patch, not a Modal feature). DinD also doubles the isolation tax (gVisor
  outer + Docker inner), is flagged experimental, and the dockerd bring-up is fragile.
- Only justified if we needed Harbor's *exact* sandbox semantics (e.g. its verifier
  container). We don't: verification is disabled and we judge traces ourselves.

### Option B — agent-direct in the Modal container (RECOMMENDED)
Drop Harbor's Docker layer. The **Modal function container *is* the sandbox.** We install
the three agent CLIs into the Modal Image, bind-mount the dataset Volume read-only at
`/app/data`, inject the subscription token via a Modal Secret, drop `instruction.md` into
`/app`, and invoke the agent CLI directly (`codex exec ...`, `claude -p ...`,
`agy --print ...`). The agent writes `/app/answer.txt` + `/app/trace.md`; we copy those back
to an outputs Volume (or return bytes).

Why B wins:
- **It is the bind-mount.** Modal volume-mounting *is* exactly the v2 goal — one apt-only
  base Image, data mounted at runtime. No per-task build, no 18 GB COPY. Build collapses to
  "pull the cached Image."
- **Isolation is already there.** Modal runs every function in its own gVisor-sandboxed
  container with no shared state — the same isolation property Harbor's Docker layer gave us.
  One agent per container = one task per container.
- **Less moving machinery.** We reimplement only the ~40 lines of auth-injection logic our
  custom agents already encode (auth.json upload, OAuth env, agy tgz extraction) as plain
  container setup. No dockerd, no gVisor networking hacks, no Harbor TOML round-trip.
- **Cost.** Standard-task CPU is **3×cheaper** than Sandbox CPU on Modal
  ($0.0000131 vs $0.00003942 /core/s). `@app.function` runs are standard-task priced; the
  DinD recipe needs the Sandbox price tier. B is the cheap tier *and* avoids the inner build.

**Decision: Option B (agent-direct).** Port the three custom Harbor agents' auth logic into
a small per-agent "runner" inside one Modal function. Keep Harbor on the Mac as the
ground-truth/fallback path; Modal v2 is the scale-out replicate path.

> Loud flag: if a future requirement forces Harbor's *verifier* container or its exact
> sandbox lifecycle, revisit Option A — but accept that DinD reintroduces the per-task image
> build we're trying to delete, so the bind-mount goal would then need a Harbor patch.

---

## 2. Data as a Modal Volume (get 83 GB in once)

The unique dataset is **83.1 GB** (50 base datasets; variants are perturbations of those,
mostly small edits/drops on top of a shared base). One Volume, populated once, mounted
read-only into every run.

### Layout in the Volume
```
biomnibench-data   (modal.Volume, v2)
└── tasks/
    ├── da-1-3_drop_tissue/        # full per-task environment/data, as Harbor assembled it
    │   ├── GSE236581_counts.mtx
    │   └── ...
    ├── da-1-3_single_tissue/
    └── ... (one dir per task; 109 variant + ~50 base)
```
We mount the *task's own* data subdir read-only at `/app/data`, so the agent sees an
identical filesystem to v1's `/app/data`. (Optionally dedup: store the 50 base datasets once
under `base/<da-N-M>/` and the variant deltas under `tasks/<variant>/`, then assemble at
runtime. Simplest correct first cut = one dir per task; revisit dedup only if the 83 GB
upload time or the 1 TiB free-storage ceiling bites — it won't: 83 GB ≪ 1 TiB.)

### Getting it in (one-time, ~free)
Two options, both run from the Mac that already has the assembled tree:

1. **CLI (simplest):**
   ```bash
   modal volume create biomnibench-data --version=2
   modal volume put biomnibench-data runs/harbor_tasks/<task>/environment/data tasks/<task>
   # loop over tasks, or put the whole assembled tree in one shot
   ```
2. **Programmatic batch upload** (resumable, scriptable — see `app.py:upload_dataset`):
   ```python
   vol = modal.Volume.from_name("biomnibench-data", create_if_missing=True)
   with vol.batch_upload() as batch:
       batch.put_directory(local_task_data, f"tasks/{task}")
   ```

Upload is **bandwidth-bound, not compute-billed** — you pay only storage after it lands.
83 GB at, say, 50 Mbit/s home upload ≈ ~3.7 h wall once; at gigabit ≈ ~12 min.
**Storage cost: 83 GiB × $0.09/GiB/mo = ~$7.50/mo, but the first 1 TiB/mo is free → $0.**

> If COPYing 18 GB tasks from the Mac is the slow part today, note the upload happens **once**
> ever, not per run — that is the whole point of v2.

---

## 3. The Image (apt-only base + agent CLIs)

One Image, built once, cached by Modal. No data in it.

```
modal.Image.from_registry("ubuntu:24.04")
  .apt_install("python3","python3-pip","python3-venv","r-base","r-base-dev",
               "curl","wget","git","ca-certificates","nodejs","npm")
  .pip_install(<scientific python the tasks expect: scanpy, anndata, pandas,
               scipy, numpy, openpyxl, statsmodels, ...>)   # was implicit in v1 via apt python3 + agent self-install; pin it here
  .run_commands(
     "npm i -g @openai/codex@0.135.0",                       # codex CLI
     "npm i -g @anthropic-ai/claude-code",                   # claude-code CLI
     "curl -fsSL https://.../agy-install.sh | bash",         # antigravity CLI (agy)
  )
```
This mirrors the v1 Dockerfile's `apt-get install python3 r-base ...` exactly, minus the
`COPY data` lines (those become the Volume mount). Agent CLIs that Harbor used to install
*inside* the sandbox at run time move into the Image build so every run starts warm.

---

## 4. Auth / secret injection for the 3 subscriptions

We never put an API key in the container for billing — all three run on **subscriptions**.
Port each custom agent's injection into container setup, fed by **Modal Secrets**:

| Agent | Secret contents | In-container setup (what the function does) | Env at exec |
|---|---|---|---|
| codex | `codex-auth` secret carrying the **contents** of `~/.codex/auth.json` (as one var, e.g. `CODEX_AUTH_JSON`) | write `$CODEX_HOME/auth.json` from the secret var, `chmod 600` | `CODEX_FORCE_AUTH_JSON=1`, **unset** `OPENAI_API_KEY` |
| claude-code | `claude-oauth` secret with `CLAUDE_CODE_OAUTH_TOKEN` | nothing — CLI reads the env directly | `CLAUDE_CODE_OAUTH_TOKEN=...`, **unset** `ANTHROPIC_API_KEY` (force `apiKeySource=none`) |
| antigravity | `agy-token` secret — the captured `agy_token_store.tgz` is binary, so store it base64 in a var (`AGY_TOKEN_STORE_B64`) **or** put the tgz in the data Volume under `auth/agy_token_store.tgz` | base64-decode → untar → place `antigravity-oauth-token` + `installation_id` in `~/.gemini/antigravity-cli/` (0600); write `settings.json` w/ model display name + trusted workspaces | (agy reads token from disk) |

Create secrets once:
```bash
modal secret create codex-auth   CODEX_AUTH_JSON="$(cat ~/.codex/auth.json)"
modal secret create claude-oauth  CLAUDE_CODE_OAUTH_TOKEN="$CC_OAUTH_TOKEN"
modal secret create agy-token      AGY_TOKEN_STORE_B64="$(base64 < runs/harbor_auth/agy_token_store.tgz)"
```
A function attaches **only the one secret for the agent it's running** via
`secrets=[modal.Secret.from_name(...)]`, so a codex run never sees the Claude token. The
"strip the other providers' API keys" hygiene from `run_base_matrix.sh` is preserved by
simply *not* attaching those secrets and unsetting the keys before exec.

> Token freshness: codex `auth.json` and the agy token carry refresh credentials (durable);
> the claude OAuth token is long-lived. Re-`modal secret create` (overwrites) when any rotates.

---

## 5. Parallelism model (bounded by per-subscription rate limits)

The hard constraint from v1: **one arm per subscription account at a time.** So the
parallelism is **across the 3 accounts**, plus the fact that v2 has *no per-task build to
serialize on*. Concretely:

- **3 concurrent lanes**, one per agent (`codex`, `claude-code`, `antigravity`). Within a
  lane, tasks run **sequentially** (or with the same paced/back-off discipline as
  `run_variant_matrix.sh`: pace between cells, exponential backoff + retry on 429/403,
  batch cooldown every N cells).
- Enforce on Modal with **per-agent `max_containers=1`** (one function variant per agent, or
  one function keyed by agent with a concurrency cap), so `.map()` over a lane's tasks still
  executes one-at-a-time but Modal handles queueing/retries/logging.
- The three lanes run **in parallel** (3 containers max system-wide for agent work) because
  they hit independent accounts. Builds are free/instant (cached Image), so there's no build
  fan-out to manage — the v1 "build is the bottleneck" problem disappears.
- This is the *opposite* of typical Modal usage (which maxes `.map()` width). Here width is
  **rate-limit-capped at 1 per account**, and Modal's value is reliability/observability/zero
  local disk, not raw concurrency.

```python
@app.function(image=IMG, volumes={"/data": data_vol}, max_containers=1,
              secrets=[...per-agent...], timeout=3600, retries=2)
def run_task(spec): ...
# lane = run_task.map(specs_for_one_agent)   # serial within agent, 3 lanes in parallel
```

If a subscription's ceiling ever proves to tolerate 2 concurrent, bump that one lane's
`max_containers`; the model is per-lane, not global.

---

## 6. $500 budget estimate

**Per-task compute cost (Option B, standard-task pricing):**
- CPU: tasks are CPU-only, data-analysis. Assume **2 cores** requested.
  `2 × $0.0000131 /core/s = $0.0000262 /s`.
- Memory: single-cell `.mtx`/`.h5ad` work needs headroom; assume **16 GiB**.
  `16 × $0.00000222 /GiB/s = $0.0000355 /s`.
- Combined ≈ **$0.0000617 /s ≈ $0.222 /hour** of wall-clock per running task.

**Per-task wall time:** agent timeout is 3600 s, but typical completions are far shorter.
Use a planning average of **~20 min (1200 s)** active per task (refusal/data-analysis tasks
finish or refuse well under the hour cap; some run long).

- **Cost per task-run ≈ 1200 s × $0.0000617 = ~$0.074** (~7.4 cents).
- Round up to **~$0.10/task-run** to absorb cold-start, occasional long tasks, retries.

**Matrix size:** ~109 variant + ~50 base ≈ **~160 task cells per agent × 3 agents = ~480
task-runs for one full pass (1 replicate).**

- One full replicate ≈ **480 × $0.10 ≈ $48.**
- Volume storage: **$0/mo** (83 GiB < 1 TiB free tier). Negligible even if it weren't (~$7.50/mo).
- Egress/artifacts (answer.txt + trace.md, a few KB each): negligible.

**$500 buys roughly:**
- **~10 full replicates** of the entire 3-agent × ~160-task matrix
  ($500 ÷ $48 ≈ 10.4), **with comfortable headroom** for retries, the paced back-off
  re-runs, and judge/processing functions.
- Equivalently **~5,000 individual task-runs** at $0.10 each.

**Sensitivity:** if the realistic average is the full 1 h cap (worst case, every task runs to
timeout) cost/task ≈ $0.22 → one replicate ≈ $107 → **~4–5 replicates** in $500. If tasks
average 10 min, ~$0.04/task → one replicate ≈ $20 → **~20+ replicates**. So the honest
range is **~5–20 full replicates**, planning number **~10**.

> The single biggest cost lever is wall-time per task (the agent timeout), **not** the
> dataset or the build — which is exactly why eliminating the 18 GB build (v2) and not paying
> the 3× Sandbox CPU tier (Option B) matters. Spend the smoke test first (VALIDATION-PLAN.md)
> to measure the *real* average task wall time before committing to N replicates.

---

## 7. Open items / TODOs to resolve before a real run
- **Pin the scientific Python stack** the tasks expect (v1 leaned on apt `python3` + agent
  self-install). List exact deps from a representative `instruction.md` + `tests/`.
- **agy installer URL** and that agy runs headless under gVisor with the injected token
  (validate in the smoke test — this is the riskiest of the three CLIs).
- **Outputs path:** return `(answer, trace)` bytes from the function (simplest) vs. write to a
  separate `biomnibench-out` Volume keyed by `agent/task/replicate`. Prototype returns bytes.
- **Network mode:** v1 tasks are `network_mode="public"` (agents need internet for the
  subscription backends). Modal functions have egress by default — fine. No `none`-network
  tasks in this matrix.
- **Trace capture parity:** Harbor tee'd the raw agent transcript to `/logs/agent/...`. In B
  we capture stdout/stderr of the CLI exec ourselves and save alongside answer/trace.
