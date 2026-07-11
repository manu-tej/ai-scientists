# orchestration/

Personal-infra helper scripts for driving the benchmark runs across a laptop
and a remote Docker host. **These are not part of the benchmark itself** and are
not required to reproduce any result — they are operational glue (batch drivers,
session-limit retry loops, laptop↔remote sync) tuned to one particular machine
setup.

The reproducible entry points live elsewhere: see the repo `README.md` Quickstart,
`RESULTS.md`, and `bench/README.md`. The scripts here assume a flat deploy
directory (`$HOME/benchbench`) and a configured SSH host alias (`remote`); paths
and hostnames are placeholders you must adapt to your own environment.

| Script | Purpose |
|---|---|
| `run_base_matrix.sh` | Single-pass capability-baseline runner over the base task tree. |
| `run_until_complete.sh` | Re-runs `run_base_matrix.sh` until every task has a real verifier reward. |
| `run_cc_batch.sh` | claude-code baseline in session-limited batches (purges poisoned cells). |
| `run_cc_parallel.sh` | Size-aware parallel claude-code baseline (light tasks wide, heavy tasks solo). |
| `run_mac_cc.sh` | Laptop claude-code arm with a hard billing auth-gate (fails closed). |
| `sync_to_remote.sh` | Pushes laptop-completed cells to the remote host so its skip-guard skips them. |

Related helpers kept under `scripts/` (grading/status utilities): `regrade_remote.sh`,
`collect_status.py`, `progress_server.py`, `run_variant_matrix.sh`.
