#!/usr/bin/env bash
# Backfill the claude-code cells that hit the Claude session limit (429) on the
# first matrix pass. Uses the FRESH CC_OAUTH_TOKEN from .env. Sequential to avoid
# a session-limit burst + Colima contention; per-task output dir (collision-safe,
# idempotent: skips cells already completed).
set -uo pipefail
cd "$(dirname "$0")/.."
set -a; . ./.env; set +a
[ -n "${CC_OAUTH_TOKEN:-}" ] || { echo "CC_OAUTH_TOKEN missing"; exit 1; }

OUT="runs/harbor_matrix_cc"
TASKS=(da-13-3_drop_pvalues da-5-1_drop_tier da-13-3_drop_pct_fat da-17-1_drop_disease)

for task in "${TASKS[@]}"; do
  out="$OUT/$task"
  if compgen -G "$out/*/*/result.json" >/dev/null 2>&1; then
    echo "SKIP $task (already complete)"; continue
  fi
  mkdir -p "$out"
  echo "=== claude-code $task $(date +%H:%M:%S) ==="
  env -u ANTHROPIC_API_KEY -u OPENAI_API_KEY -u GEMINI_API_KEY \
    CLAUDE_CODE_OAUTH_TOKEN="$CC_OAUTH_TOKEN" \
    harbor run --path "runs/harbor_tasks/$task" --agent claude-code --model claude-opus-4-7 \
    --disable-verification -n 1 -o "$out" >>"/tmp/cc_${task}.log" 2>&1
  echo "    done $task $(date +%H:%M:%S)"
done
echo "CC BACKFILL COMPLETE (${#TASKS[@]} tasks)"
