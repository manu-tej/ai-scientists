"""Modal v2 harness for the BiomniBench-DA refusal matrix — PROTOTYPE / SKELETON.

DO NOT RUN BLINDLY. This is runnable-in-principle but has placeholders (marked TODO)
where our exact task format, agent-CLI invocation, and scientific-Python deps plug in.
Read modal_v2/DESIGN.md first. Nothing here has been executed; spend the smoke test in
VALIDATION-PLAN.md (a few cents) before any matrix run.

Architecture: Option B (agent-direct). The Modal function container IS the sandbox.
  - one apt-only Image with the three agent CLIs baked in (NO data in the image)
  - the dataset lives once in a Modal Volume, mounted READ-ONLY at /data
  - subscription auth comes from Modal Secrets (one per agent), never an API key
  - parallelism = 3 lanes (one per subscription account), max_containers=1 PER LANE,
    because each subscription rate-limits a second concurrent arm (see DESIGN.md §5).

Layout expected in the data Volume (populated once via `upload_dataset` or `modal volume put`):
    biomnibench-data/
      tasks/<task>/...            # the per-task environment/data tree, as Harbor assembled it
      meta/<task>/instruction.md  # the instruction.md (affordance already appended)  [TODO]
      auth/agy_token_store.tgz    # optional: agy token store, if not shipped via Secret
"""
from __future__ import annotations

import base64
import io
import os
import shlex
import subprocess
import tarfile
import time
from pathlib import Path

import modal

# --------------------------------------------------------------------------------------
# Names (create these once; see CLI snippets in DESIGN.md §2 and §4).
# --------------------------------------------------------------------------------------
APP_NAME = "biomnibench-v2"
DATA_VOLUME = "biomnibench-data"          # v2 Volume holding the 83 GB dataset (read-only mount)
OUT_VOLUME = "biomnibench-out"            # optional: durable outputs (answer/trace/transcript)

DATA_MNT = "/data"                        # where the whole dataset Volume mounts (read-only)
OUT_MNT = "/out"                          # where the outputs Volume mounts (read-write)
APP_DIR = "/app"                          # working dir the agents see (mirrors v1 /app)

app = modal.App(APP_NAME)

# Read-only mount of the dataset; outputs Volume is read-write.
data_vol = modal.Volume.from_name(DATA_VOLUME, create_if_missing=True)
out_vol = modal.Volume.from_name(OUT_VOLUME, create_if_missing=True)

# --------------------------------------------------------------------------------------
# Image: apt-only base + agent CLIs. Mirrors the v1 Dockerfile MINUS `COPY data` (that
# becomes the Volume mount). NO dataset is baked in -> builds are tiny and cached.
# --------------------------------------------------------------------------------------
AGENT_IMAGE = (
    modal.Image.from_registry("ubuntu:24.04")
    .env({"DEBIAN_FRONTEND": "noninteractive"})
    .apt_install(
        "python3", "python3-pip", "python3-venv",
        "r-base", "r-base-dev",
        "curl", "wget", "git", "ca-certificates",
        "nodejs", "npm",
    )
    # TODO: pin the exact scientific-Python stack the tasks expect. v1 relied on apt
    # python3 + the agent self-installing; make it deterministic here. Representative set:
    .pip_install(
        "pandas", "numpy", "scipy", "statsmodels",
        "scanpy", "anndata", "openpyxl",            # single-cell .mtx/.h5ad + .xlsx clinical
        # TODO: add/remove to match runs/harbor_tasks/*/instruction.md + tests/ requirements
    )
    .run_commands(
        # Agent CLIs baked into the image so every run starts warm (Harbor used to install
        # these inside the sandbox at run time).
        "npm install -g @openai/codex@0.135.0",                 # codex CLI (matches v1 0.135.0)
        "npm install -g @anthropic-ai/claude-code",             # claude-code CLI
        # TODO: confirm the agy (antigravity-cli) install command + that it runs headless.
        # "curl -fsSL https://<agy-installer-url> | bash",
    )
)


# ======================================================================================
# ONE-TIME: upload the assembled dataset into the Volume (run from the Mac, ~free).
# Bandwidth-bound, not compute-billed. Alternatively use `modal volume put` (DESIGN.md §2).
# ======================================================================================
@app.local_entrypoint()
def upload_dataset(tasks_root: str = "runs/harbor_tasks"):
    """Push runs/harbor_tasks/<task>/environment/data -> Volume tasks/<task>/, and
    instruction.md -> meta/<task>/instruction.md. Run once; storage is the only ongoing cost
    (83 GiB < 1 TiB free tier => $0/mo). Idempotent-ish: re-running re-puts.

    Usage:  modal run modal_v2/app.py::upload_dataset --tasks-root runs/harbor_tasks
    """
    root = Path(tasks_root)
    task_dirs = sorted(d for d in root.iterdir() if (d / "task.toml").exists())
    print(f"uploading {len(task_dirs)} tasks from {root} into Volume '{DATA_VOLUME}'")
    with data_vol.batch_upload(force=True) as batch:
        for d in task_dirs:
            task = d.name
            data_dir = d / "environment" / "data"
            if data_dir.is_dir():
                batch.put_directory(str(data_dir), f"tasks/{task}")
            instr = d / "instruction.md"
            if instr.is_file():
                batch.put_file(str(instr), f"meta/{task}/instruction.md")
    print("upload complete. Verify with: modal volume ls biomnibench-data tasks")


# ======================================================================================
# Per-agent auth injection inside the container (ports the 3 custom Harbor agents' logic).
# Secrets are attached per-function-call (DESIGN.md §4); each agent sees only its own.
# ======================================================================================
def _setup_codex_auth() -> dict[str, str]:
    """codex: write $CODEX_HOME/auth.json from secret, force auth.json, drop OPENAI_API_KEY.

    Mirrors Harbor codex.py (CODEX_FORCE_AUTH_JSON + auth.json upload) and our
    CodexNoImagegen (image_generation off). Secret `codex-auth` carries CODEX_AUTH_JSON.
    """
    codex_home = "/tmp/codex-home"
    os.makedirs(codex_home, exist_ok=True)
    auth = os.environ.get("CODEX_AUTH_JSON")
    if not auth:
        raise RuntimeError("CODEX_AUTH_JSON missing (attach Secret 'codex-auth')")
    p = Path(codex_home) / "auth.json"
    p.write_text(auth)
    p.chmod(0o600)
    env = dict(os.environ)
    env["CODEX_HOME"] = codex_home
    env["CODEX_FORCE_AUTH_JSON"] = "1"
    env.pop("OPENAI_API_KEY", None)          # subscription, never API key
    return env


def _setup_claude_auth() -> dict[str, str]:
    """claude-code: env CLAUDE_CODE_OAUTH_TOKEN; strip ANTHROPIC_API_KEY (apiKeySource=none)."""
    if not os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"):
        raise RuntimeError("CLAUDE_CODE_OAUTH_TOKEN missing (attach Secret 'claude-oauth')")
    env = dict(os.environ)
    env.pop("ANTHROPIC_API_KEY", None)       # else it bills the API instead of the Max sub
    env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] = "1"
    return env


def _setup_agy_auth() -> dict[str, str]:
    """antigravity (agy): extract the captured Linux token store into ~/.gemini/antigravity-cli/.

    Ports antigravity_oauth.py: place antigravity-oauth-token + installation_id (0600) and
    write settings.json (model display name + trusted workspaces). Token source: base64 in
    Secret `agy-token` (AGY_TOKEN_STORE_B64) OR the data Volume at auth/agy_token_store.tgz.
    """
    agy_dir = Path.home() / ".gemini" / "antigravity-cli"
    agy_dir.mkdir(parents=True, exist_ok=True)

    b64 = os.environ.get("AGY_TOKEN_STORE_B64")
    vol_tgz = Path(DATA_MNT) / "auth" / "agy_token_store.tgz"
    if b64:
        tgz_bytes = base64.b64decode(b64)
        tf = tarfile.open(fileobj=io.BytesIO(tgz_bytes), mode="r:gz")
    elif vol_tgz.is_file():
        tf = tarfile.open(vol_tgz, mode="r:gz")
    else:
        raise RuntimeError("agy token store not found (Secret AGY_TOKEN_STORE_B64 or Volume auth/agy_token_store.tgz)")

    with tf:
        names = set(tf.getnames())
        token_member = ".gemini/antigravity-cli/antigravity-oauth-token"
        if token_member not in names:
            raise RuntimeError(f"token store missing {token_member}; recapture with agy_login_capture.sh")
        for member, dest in (
            (token_member, "antigravity-oauth-token"),
            (".gemini/antigravity-cli/installation_id", "installation_id"),
        ):
            if member in names:
                src = tf.extractfile(member)
                if src is not None:
                    out = agy_dir / dest
                    out.write_bytes(src.read())
                    out.chmod(0o600)

    # settings.json: model display name + trusted workspaces (see antigravity_oauth.py).
    model_display = os.environ.get("AGY_MODEL_DISPLAY", "Gemini 3.1 Pro (High)")  # TODO confirm
    import json
    (agy_dir / "settings.json").write_text(json.dumps({
        "enableTelemetry": False,
        "model": model_display,
        "trustedWorkspaces": ["/", APP_DIR, "/workspace"],
        "experimental": {"skills": True},
    }, indent=2))
    return dict(os.environ)


# ======================================================================================
# Per-agent CLI invocation (replaces Harbor's sandbox exec). Each returns (cmd, env).
# TODO: confirm exact flags/headless print-mode against the installed CLI versions.
# ======================================================================================
def _agent_command(agent: str, instruction_path: str) -> tuple[list[str], dict[str, str]]:
    if agent == "codex":
        env = _setup_codex_auth()
        # v1: model gpt-5.5, image_generation disabled, read instruction, work in /app.
        cmd = [
            "codex", "exec",
            "-c", "features.image_generation=false",     # CodexNoImagegen
            "-c", "model_reasoning_effort=high",          # TODO match v1 default
            "--model", "gpt-5.5",
            "--cd", APP_DIR,
            f"@{instruction_path}",                       # TODO confirm codex exec prompt-file syntax
        ]
        return cmd, env
    if agent == "claude-code":
        env = _setup_claude_auth()
        cmd = [
            "claude", "-p",                               # print/non-interactive
            "--model", "claude-opus-4-7",                 # v1 model
            "--dangerously-skip-permissions",
            # TODO: confirm how to pass the instruction file + working dir to claude-code CLI
        ]
        return cmd, env
    if agent == "antigravity":
        env = _setup_agy_auth()
        pt = os.environ.get("AGY_PRINT_TIMEOUT", "50m")  # antigravity_oauth.py protection
        cmd = [
            "agy", "--print", f"--print-timeout={pt}",
            "--dangerously-skip-permissions",
            # TODO: confirm agy print-mode prompt/instruction + working dir flags
        ]
        return cmd, env
    raise ValueError(f"unknown agent {agent!r}")


# ======================================================================================
# The one function: mount data, set up auth, run ONE agent on ONE task, capture outputs.
# max_containers=1 -> serial WITHIN a lane (per-subscription rate limit, DESIGN.md §5).
# Run 3 of these lanes in parallel (one per agent) from the local entrypoint.
# ======================================================================================
def _run_task_impl(spec: dict) -> dict:
    """spec = {"agent": str, "task": str, "replicate": int}. Returns a result dict with
    answer/trace bytes + the raw transcript. Pure-ish: reads /data (ro), writes /app (tmp)."""
    agent, task, rep = spec["agent"], spec["task"], spec.get("replicate", 0)

    # 1. Assemble /app exactly like v1: data at /app/data (from the Volume), instruction.md.
    workdir = Path(APP_DIR)
    (workdir / "data").mkdir(parents=True, exist_ok=True)
    # Bind-mount equivalent: symlink the read-only Volume task data into /app/data.
    # (Symlink, not copy -> zero extra disk; the agent reads through it transparently.)
    src_data = Path(DATA_MNT) / "tasks" / task
    # TODO: if a task needs a writable data dir, copy instead; most are read-only inputs.
    for p in src_data.rglob("*"):
        rel = p.relative_to(src_data)
        dst = workdir / "data" / rel
        if p.is_dir():
            dst.mkdir(parents=True, exist_ok=True)
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            if not dst.exists():
                os.symlink(p, dst)

    instruction_path = str(Path(DATA_MNT) / "meta" / task / "instruction.md")
    if not Path(instruction_path).is_file():
        # Fallback: instruction shipped inside the task dir. TODO finalize where it lives.
        instruction_path = str(workdir / "instruction.md")

    # 2. Build the agent command + env (auth injected here).
    cmd, env = _agent_command(agent, instruction_path)

    # 3. Run the agent CLI directly in this container (no Harbor, no inner Docker).
    t0 = time.time()
    proc = subprocess.run(
        cmd, cwd=str(workdir), env=env,
        capture_output=True, text=True,
        timeout=int(os.environ.get("AGENT_TIMEOUT_SEC", "3600")),  # v1 agent.timeout_sec
    )
    elapsed = time.time() - t0
    transcript = (proc.stdout or "") + "\n----STDERR----\n" + (proc.stderr or "")

    # 4. Capture deliverables (v1: /app/answer.txt + /app/trace.md).
    answer = (workdir / "answer.txt")
    trace = (workdir / "trace.md")
    result = {
        "agent": agent, "task": task, "replicate": rep,
        "returncode": proc.returncode, "elapsed_sec": round(elapsed, 1),
        "answer": answer.read_text() if answer.is_file() else None,
        "trace": trace.read_text() if trace.is_file() else None,
        "transcript": transcript,
    }

    # 5. Persist to the outputs Volume (durable, keyed by agent/task/replicate).
    out_dir = Path(OUT_MNT) / agent / task / f"rep{rep}"
    out_dir.mkdir(parents=True, exist_ok=True)
    if result["answer"] is not None:
        (out_dir / "answer.txt").write_text(result["answer"])
    if result["trace"] is not None:
        (out_dir / "trace.md").write_text(result["trace"])
    (out_dir / "transcript.txt").write_text(transcript)
    out_vol.commit()
    return {k: v for k, v in result.items() if k != "transcript"}  # keep return payload small


# Three function variants, one per agent, each pinned to its own Secret and max_containers=1.
# Splitting by agent lets the 3 lanes run in parallel while each lane stays serial (the
# per-subscription rate-limit constraint). Same impl, different secret + name.
_COMMON = dict(
    image=AGENT_IMAGE,
    volumes={DATA_MNT: data_vol, OUT_MNT: out_vol},
    timeout=3600,
    retries=2,                  # Modal-level retry; in-lane back-off handled by entrypoint
    max_containers=1,           # SERIAL within this agent's lane (rate-limit ceiling)
    cpu=2.0,                    # CPU-only tasks; tune from smoke-test measurements
    memory=16384,               # 16 GiB headroom for single-cell .mtx/.h5ad
)


@app.function(secrets=[modal.Secret.from_name("codex-auth")], **_COMMON)
def run_codex(spec: dict) -> dict:
    return _run_task_impl({**spec, "agent": "codex"})


@app.function(secrets=[modal.Secret.from_name("claude-oauth")], **_COMMON)
def run_claude(spec: dict) -> dict:
    return _run_task_impl({**spec, "agent": "claude-code"})


@app.function(secrets=[modal.Secret.from_name("agy-token")], **_COMMON)
def run_agy(spec: dict) -> dict:
    return _run_task_impl({**spec, "agent": "antigravity"})


_LANE = {"codex": run_codex, "claude-code": run_claude, "antigravity": run_agy}


# ======================================================================================
# Local entrypoint: map tasks per lane. The 3 lanes run in parallel; each lane is serial
# (max_containers=1). Mirrors the 3-arm matrix in run_variant_matrix.sh / run_base_matrix.sh.
# ======================================================================================
@app.local_entrypoint()
def run_matrix(
    agents: str = "codex,claude-code,antigravity",
    tasks: str = "",            # comma-sep task names; empty => TODO: list from the Volume
    replicates: int = 1,
):
    """Fan out the matrix across the 3 subscription lanes.

    Usage (smoke, one cell): modal run modal_v2/app.py::run_matrix \\
        --agents codex --tasks da-1-3_drop_tissue --replicates 1

    Full pass: --agents codex,claude-code,antigravity --tasks <...all...> --replicates N
    """
    agent_list = [a.strip() for a in agents.split(",") if a.strip()]
    task_list = [t.strip() for t in tasks.split(",") if t.strip()]
    if not task_list:
        # TODO: enumerate tasks from the Volume (e.g. `modal volume ls biomnibench-data tasks`).
        raise SystemExit("pass --tasks (comma-separated); auto-listing from Volume is a TODO")

    # Build per-lane input lists.
    handles = {}
    for agent in agent_list:
        fn = _LANE[agent]
        specs = [{"task": t, "replicate": r} for t in task_list for r in range(replicates)]
        # .map() within a lane: max_containers=1 makes Modal run them one-at-a-time (serial),
        # while the three .map() calls below proceed concurrently => 3 parallel lanes.
        handles[agent] = fn.map(specs)

    # Drain results (kept simple; a real run would interleave + log + apply paced back-off).
    for agent, it in handles.items():
        for res in it:
            print(f"[{agent}] {res['task']} rep{res['replicate']} "
                  f"rc={res['returncode']} {res['elapsed_sec']}s "
                  f"answer={'yes' if res['answer'] else 'NONE'}")
