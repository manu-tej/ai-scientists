#!/usr/bin/env bash
# Adversarial-variant arm, COLLECT-ONLY, subscription auth ($0). PACED + 429-AWARE:
# the ChatGPT subscription has a sustained-usage ceiling — a continuous 100+ task codex
# push hits 403/429 and corrupts traces. This runner therefore:
#   - skips only cells that already have a CLEAN trace (>=3KB, no 429) — so it re-does
#     429-corrupted cells automatically (idempotent, resumable);
#   - after each cell, inspects the trace; on 429/403 (or a tiny failure trace) it COOLS
#     DOWN and retries the cell (up to BB_RETRIES);
#   - paces between clean cells and takes a batch cooldown every BB_BATCH cells;
#   - optional BB_INITIAL_COOLDOWN up front to let the usage window reset before starting.
# Per-task Docker image+cache cleanup keeps the (mac) VM disk flat.
#
# IMPORTANT: only ONE ChatGPT-subscription codex arm may run at a time (concurrent codex
# arms rate-limit each other). agy (Google) / claude-code (Claude) are separate accounts.
#
# Usage: scripts/run_variant_matrix.sh [agent...]              # default codex
#   BB_INITIAL_COOLDOWN=3600 scripts/run_variant_matrix.sh codex   # wait 1h, then run paced
# Tunables (env): BB_PACE_SEC=45 BB_BACKOFF_SEC=1200 BB_RETRIES=3 BB_BATCH=12 BB_BATCH_COOLDOWN=900
set -uo pipefail
cd "$(dirname "$0")/.."
export PATH="$HOME/.local/bin:$PATH"
export PYTHONPATH="$PWD${PYTHONPATH:+:$PYTHONPATH}"
[ -f .env ] && { set -a; . ./.env; set +a; }
AGY_AGENT="benchmarks.harbor_agents.antigravity_oauth:AntigravityCliOAuth"
AGY_STORE="$PWD/runs/harbor_auth/agy_token_store.tgz"

AGENTS=("${@:-codex}")
OUT="runs/harbor_variant_matrix"
PACE_SEC="${BB_PACE_SEC:-45}"
BACKOFF_SEC="${BB_BACKOFF_SEC:-1200}"
RETRIES="${BB_RETRIES:-3}"
BATCH="${BB_BATCH:-12}"
BATCH_COOLDOWN="${BB_BATCH_COOLDOWN:-900}"
INITIAL_COOLDOWN="${BB_INITIAL_COOLDOWN:-0}"

TASKS=()
for d in runs/harbor_tasks/*/; do
  t=$(basename "$d")
  [ -f "$d/task.toml" ] && [ -d "$d/environment/data" ] || continue
  # Harbor needs a build definition; ~16 BiomniBench tasks ship no Dockerfile (and no
  # docker_image) so they are not buildable — skip them rather than fast-fail each cell.
  { [ -f "$d/environment/Dockerfile" ] || grep -q docker_image "$d/task.toml" 2>/dev/null; } || continue
  TASKS+=("$t")
done

cleanup_task() {
  local pfx="${1:0:30}"
  # CONCURRENCY-SAFE: multiple agent arms (codex/cc/agy) may run the SAME task name at once.
  # Reap only EXITED containers (never kill another arm's running container), and remove a
  # task image only if NO running container is using it.
  docker ps -aq --filter "name=${pfx}" --filter status=exited 2>/dev/null \
    | xargs -r docker rm -f >/dev/null 2>&1 || true
  for img in $(docker images --format '{{.ID}} {{.Repository}}' 2>/dev/null \
                | awk -v p="$pfx" 'index($2,p)==1{print $1}'); do
    [ -z "$(docker ps -q --filter ancestor="$img" 2>/dev/null)" ] \
      && docker rmi -f "$img" >/dev/null 2>&1 || true
  done
  # Builder-cache prune is needed ONLY on the mac (fixed Docker-VM disk cascades). On a
  # native-Linux host with ample disk (serene), pruning every task destroys the shared
  # apt+codex base layer and forces a full reinstall per build. Opt out with BB_PRUNE_BUILDER=0.
  [ "${BB_PRUNE_BUILDER:-1}" = "1" ] && docker builder prune -f >/dev/null 2>&1 || true
}

# A cell is DONE if it delivered a real answer.txt. With imagegen disabled (CodexNoImagegen)
# clean runs reliably write artifacts/answer.txt + artifacts/trace.md; a 403/429-failed run
# writes NO answer.txt (or a tiny error stub), so answer.txt presence is the done-signal.
# (We still scan trial.log for a hard rate-limit that slipped through, to be safe.)
has_clean_trace() {
  local out="$OUT/$1/$2" af
  af=$(find "$out" -path '*artifacts*' -name answer.txt 2>/dev/null | head -1)
  [ -n "$af" ] || return 1
  [ "$(wc -c <"$af" 2>/dev/null)" -ge 80 ] || return 1
  # a run that 403/429'd mid-flight may still leave a stub answer; reject if the log shows it
  find "$out" -name 'trial.log' -exec grep -qlE '429 Too Many|403 Forbidden' {} + 2>/dev/null && return 1
  return 0
}

run_harbor() {  # $1 agent $2 task -> runs one harbor trial into $OUT/agent/task
  local agent="$1" task="$2" path="runs/harbor_tasks/$2" out="$OUT/$1/$2"
  rm -rf "$out"; mkdir -p "$out"          # fresh dir each attempt (avoid stale result.json)
  local log="/tmp/var_${agent}_${task}.log"
  case "$agent" in
    codex) env -u ANTHROPIC_API_KEY -u OPENAI_API_KEY -u GEMINI_API_KEY CODEX_FORCE_AUTH_JSON=1 \
        harbor run --yes --path "$path" \
        --agent-import-path benchmarks.harbor_agents.codex_no_imagegen:CodexNoImagegen \
        --model gpt-5.5 --disable-verification -n 1 -o "$out" >>"$log" 2>&1 ;;
    claude-code) env -u ANTHROPIC_API_KEY -u OPENAI_API_KEY -u GEMINI_API_KEY \
        CLAUDE_CODE_OAUTH_TOKEN="${CC_OAUTH_TOKEN:-}" \
        harbor run --yes --path "$path" --agent claude-code --model claude-opus-4-7 \
        --disable-verification -n 1 -o "$out" >>"$log" 2>&1 ;;
    antigravity-cli) env -u ANTHROPIC_API_KEY -u OPENAI_API_KEY -u GEMINI_API_KEY -u GOOGLE_API_KEY \
        AGY_FORCE_OAUTH=1 AGY_TOKEN_STORE="$AGY_STORE" \
        harbor run --yes --path "$path" --agent-import-path "$AGY_AGENT" \
        --model gemini/gemini-3.1-pro-preview --disable-verification -n 1 -o "$out" >>"$log" 2>&1 ;;
    *) echo "unknown agent: $agent"; return 9 ;;
  esac
  cleanup_task "$task"
  has_clean_trace "$agent" "$task" && return 0 || return 1   # 0=clean, 1=429/failed
}

echo "variant matrix [collect-only, PACED]: agents=[${AGENTS[*]}] tasks=${#TASKS[@]} pace=${PACE_SEC}s backoff=${BACKOFF_SEC}s batch=${BATCH}/${BATCH_COOLDOWN}s"
if [ "$INITIAL_COOLDOWN" -gt 0 ]; then
  echo "=== initial cooldown ${INITIAL_COOLDOWN}s (let usage window reset) $(date +%H:%M:%S) ==="
  sleep "$INITIAL_COOLDOWN"
fi

for agent in "${AGENTS[@]}"; do
  n=0
  for task in "${TASKS[@]}"; do
    if has_clean_trace "$agent" "$task"; then echo "SKIP $agent/$task (clean trace)"; continue; fi
    ok=0
    for attempt in $(seq 1 "$RETRIES"); do
      echo "=== $agent $task (try $attempt) $(date +%H:%M:%S) ==="
      if run_harbor "$agent" "$task"; then echo "    clean $agent/$task $(date +%H:%M:%S)"; ok=1; break; fi
      echo "    429/failed $agent/$task — cooldown ${BACKOFF_SEC}s $(date +%H:%M:%S)"
      sleep "$BACKOFF_SEC"
    done
    [ "$ok" = 0 ] && echo "    GAVE UP $agent/$task after $RETRIES tries (leaving last trace)"
    n=$((n+1))
    if [ $((n % BATCH)) -eq 0 ]; then
      echo "=== batch cooldown ${BATCH_COOLDOWN}s after $n cells $(date +%H:%M:%S) ==="
      sleep "$BATCH_COOLDOWN"
    else
      sleep "$PACE_SEC"
    fi
  done
done
echo "VARIANT MATRIX COMPLETE (paced) $(date +%H:%M:%S)"
