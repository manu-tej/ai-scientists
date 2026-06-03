#!/usr/bin/env bash
# Resume the PAUSED 3-agent variant (refusal) run.
#
# HOW RESUME WORKS: the run's state is the COLLECTED DATA on disk
# (runs/harbor_variant_matrix/<agent>/<task>/.../artifacts/answer.txt), NOT any process.
# run_variant_matrix.sh's skip-guard (has_clean_trace: a real answer.txt with no 403/429)
# skips every cell already collected and re-runs only the rest. So relaunching the arms
# picks up exactly where the pause left off — nothing already done is recomputed, nothing is
# lost. The 109 task dirs (runs/harbor_tasks) and all collected answers are untouched by the
# baseline run (which uses runs/harbor_base_tasks + runs/cap3).
#
# CONSTRAINT (enforced below): never run two codex arms on one ChatGPT subscription. If the
# baseline capability run (bench/run.sh over runs/cap3) still has a codex arm live, this skips
# resuming codex and tells you — finish/stop the baseline codex arm first, then re-run.
#
# Usage:
#   scripts/resume_variants.sh                         # resume all three (codex auto-guarded)
#   scripts/resume_variants.sh claude-code antigravity-cli   # resume just these
set -uo pipefail
cd "$(dirname "$0")/.."

if [ $# -eq 0 ]; then AGENTS=(codex claude-code antigravity-cli); else AGENTS=("$@"); fi

for a in "${AGENTS[@]}"; do
  # already resuming this variant arm?
  if pgrep -f "run_variant_matrix.sh $a" >/dev/null; then
    echo "SKIP $a — variant arm already running"; continue
  fi
  # codex single-arm guard: don't start a 2nd codex against the same ChatGPT sub
  if [ "$a" = codex ] && pgrep -f "bench/run.sh .*--agents codex" >/dev/null; then
    echo "SKIP codex — a baseline codex arm is live (one codex arm per subscription). Stop it first."
    continue
  fi
  setsid env BB_PRUNE_BUILDER=0 BB_PACE_SEC=5 BB_BATCH_COOLDOWN=0 BB_INITIAL_COOLDOWN=0 \
    bash scripts/run_variant_matrix.sh "$a" > "/tmp/variant_$a.log" 2>&1 < /dev/null &
  echo "RESUMED $a (skips already-collected cells; logs -> /tmp/variant_$a.log)"
done
