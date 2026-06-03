# Modal v2 — cheapest smoke test (validate the path before scaling)

Goal: prove the **agent-direct + Volume bind-mount** path works end-to-end for a *single*
agent on a *single* tiny task, for **a few cents**, before committing any of the $500 to a
matrix run. This measures the two unknowns that drive cost and risk:
1. real per-task **wall time** (the dominant cost lever — DESIGN.md §6), and
2. that subscription **auth + the agent CLI** actually run headless under Modal/gVisor.

Pick a **small-data** task so the test stays cheap (avoid the 18 GB single-cell ones for the
first smoke; e.g. a clinical-`.xlsx`-only task). Confirm the chosen task's data size first:
```bash
du -sh runs/harbor_tasks/<small-task>/environment/data
```

---

## Step 0 — one-time setup (no per-run compute cost)

```bash
# (a) auth secrets (subscriptions only; see DESIGN.md §4)
modal secret create codex-auth   CODEX_AUTH_JSON="$(cat ~/.codex/auth.json)"
# (claude/agy secrets only needed when you smoke those agents)

# (b) create the Volume and upload ONLY the smoke task (cheap, fast — not all 83 GB yet)
modal volume create biomnibench-data --version=2
modal volume put biomnibench-data \
  runs/harbor_tasks/<small-task>/environment/data   tasks/<small-task>
modal volume put biomnibench-data \
  runs/harbor_tasks/<small-task>/instruction.md     meta/<small-task>/instruction.md
```
Cost of Step 0: **$0** (storage of a small task ≪ 1 TiB free tier; secrets are free).

---

## Step 1 — the smoke run (ONE agent, ONE task) — a few cents

```bash
modal run modal_v2/app.py::run_matrix \
  --agents codex \
  --tasks <small-task> \
  --replicates 1
```

Expected cost: **~$0.01–0.10** (one container, 2 cores + 16 GiB, for a few minutes:
`~$0.0000617/s` → 10 min ≈ $0.04). This is the only money spent to de-risk the whole path.

---

## Step 2 — verify (what "pass" means)

The run **passes** if all of:
- [ ] container started from the cached Image (no 18 GB build — confirm build was instant).
- [ ] `/app/data` was populated from the **Volume mount** (symlinks resolve; agent read the files).
- [ ] codex authed via `auth.json` on the **subscription** (no `OPENAI_API_KEY`, no API bill).
- [ ] the agent wrote `/app/answer.txt` (and ideally `trace.md`) — printed `answer=yes`.
- [ ] outputs landed in the `biomnibench-out` Volume under `codex/<small-task>/rep0/`:
      ```bash
      modal volume ls biomnibench-out codex/<small-task>/rep0
      ```
- [ ] note the printed `elapsed_sec` — this is the **real wall time** to plug into the
      DESIGN.md §6 budget and decide how many replicates $500 actually buys.

If codex passes, repeat Step 1 with `--agents claude-code` then `--agents antigravity`
(each needs its Secret from Step 0). **agy is the riskiest** (headless token + gVisor) —
smoke it explicitly before trusting it in a lane.

---

## Step 3 — only after all three smoke-pass

1. Upload the **full** dataset once (DESIGN.md §2): `modal run modal_v2/app.py::upload_dataset`.
2. Recompute the budget with the measured `elapsed_sec` average.
3. Run **one full replicate** (all tasks, 3 lanes) and reconcile actual $ against the estimate
   before launching N replicates.

> Stop rule: if the smoke run shows per-task wall time near the 3600 s cap, or auth fails
> under gVisor, **do not scale** — fix the agent invocation/timeout first. The smoke test
> exists precisely so a misconfiguration costs cents, not a chunk of the $500.
