#!/usr/bin/env bash
# Unified benchbench runner — ONE script that replaces run_base_matrix.sh,
# scripts/run_variant_matrix.sh and scripts/run_harbor_matrix.sh.
#
# Runs a (tasks x agents x replicates) matrix through Harbor on $0 SUBSCRIPTION auth, with a
# skip-guard (resume), optional codex pacing, and concurrency-safe per-task docker cleanup so
# multiple agent arms can share one host.
#
# PARAMETERS (flag or env; flags win):
#   --dataset DIR        task tree to run            (default runs/harbor_tasks)   [BB_TASKS_DIR]
#   --agents "a b c"     codex | claude-code | antigravity-cli | gemini-cli (default codex) [BB_AGENTS]
#   --replicates K       K replicate trials per task, run concurrently (harbor -k K -n K; build
#                        once, K agent runs in parallel). default 1.                 [BB_REPLICATES]
#   --out DIR            output root                 (default runs/harbor_matrix)   [BB_OUT]
#   --verify             run BiomniBench's verifier (--ve ANTHROPIC_API_KEY). Default: collect-only.
#   --max-effort         crank each agent to its max reasoning: codex reasoning_effort=high,
#                        claude-code --effort max + thinking=enabled, agy "Gemini 3.1 Pro (High)".
#   -h|--help            show this header.
#
# PACING / RESILIENCE (env; all default OFF so base/cc/agy runs are unpaced — turn on for a
# sustained sole-arm codex push, which can hit the ChatGPT-subscription rate ceiling):
#   BB_PACE_SEC=0        sleep between clean cells
#   BB_RETRIES=1         attempts per cell (retry on 403/429-style failure)
#   BB_BACKOFF_SEC=1200  sleep before a retry
#   BB_BATCH=12          cells per batch before a batch cooldown
#   BB_BATCH_COOLDOWN=0  sleep after each batch
#   BB_INITIAL_COOLDOWN=0 sleep before starting (let a usage window reset)
#   BB_PRUNE_BUILDER=1   docker builder prune per task (needed on local VM-backed Docker; set 0 on remote/native Docker)
#
# AUTH ($0, subscription only — the agent NEVER sees an API key; verifier key only via --ve):
#   codex            CODEX_FORCE_AUTH_JSON=1 + CodexNoImagegen agent (kills the imagegen-400 bug)
#   claude-code      CLAUDE_CODE_OAUTH_TOKEN (from .env CC_OAUTH_TOKEN)
#   antigravity-cli  AGY_FORCE_OAUTH=1 + captured token store (custom AntigravityCliOAuth agent)
#   gemini-cli       GEMINI_FORCE_OAUTH=1
#
# RULE: only ONE codex arm per ChatGPT subscription at a time (concurrent codex arms 429 each
# other). cc (Claude) / agy (Google) are separate accounts and may run alongside codex.
#
# Examples:
#   bench/run.sh --dataset runs/harbor_base_tasks --agents "codex claude-code antigravity-cli" --verify
#   BB_PACE_SEC=5 BB_RETRIES=3 BB_PRUNE_BUILDER=0 bench/run.sh --dataset runs/harbor_tasks --agents codex
#   bench/run.sh --dataset runs/harbor_tasks --agents claude-code --replicates 5 --out runs/harbor_variant_matrix
set -uo pipefail
cd "$(dirname "$0")/.."                                   # repo root (bench/ is under it)
export PATH="$HOME/.local/bin:$PATH"
export PYTHONPATH="$PWD${PYTHONPATH:+:$PYTHONPATH}"        # so Harbor can import our custom agents
[ -f .env ] && { set -a; . ./.env; set +a; }              # CC_OAUTH_TOKEN, judge keys, etc. (optional)

CODEX_AGENT="benchmarks.harbor_agents.codex_no_imagegen:CodexNoImagegen"
AGY_AGENT="benchmarks.harbor_agents.antigravity_oauth:AntigravityCliOAuth"
AGY_STORE="$PWD/runs/harbor_auth/agy_token_store.tgz"

# --- parameters (env defaults, flag overrides) -------------------------------------------
DATASET="${BB_TASKS_DIR:-runs/harbor_tasks}"
OUT="${BB_OUT:-runs/harbor_matrix}"
REPLICATES="${BB_REPLICATES:-1}"
VERIFY=0
MAX_EFFORT="${BB_MAX_EFFORT:-0}"
read -r -a AGENTS <<<"${BB_AGENTS:-codex}"
while [ $# -gt 0 ]; do
  case "$1" in
    --dataset) DATASET="$2"; shift 2 ;;
    --out) OUT="$2"; shift 2 ;;
    --replicates|-n) REPLICATES="$2"; shift 2 ;;
    --agents) read -r -a AGENTS <<<"$2"; shift 2 ;;
    --verify) VERIFY=1; shift ;;
    --max-effort) MAX_EFFORT=1; shift ;;
    -h|--help) sed -n '2,42p' "$0"; exit 0 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

PACE_SEC="${BB_PACE_SEC:-0}"; RETRIES="${BB_RETRIES:-1}"; BACKOFF_SEC="${BB_BACKOFF_SEC:-1200}"
BATCH="${BB_BATCH:-12}"; BATCH_COOLDOWN="${BB_BATCH_COOLDOWN:-0}"; INITIAL_COOLDOWN="${BB_INITIAL_COOLDOWN:-0}"

# --- verifier (only when --verify): key reaches ONLY the verifier, never the agent ---------
VERIFY_FLAGS=(--disable-verification)
if [ "$VERIFY" = 1 ]; then
  [ -z "${ANTHROPIC_API_KEY:-}" ] && [ -f ~/.bb_verifier_key ] && source ~/.bb_verifier_key
  [ -n "${ANTHROPIC_API_KEY:-}" ] || { echo "ANTHROPIC_API_KEY missing (needed for --verify)"; exit 1; }
  VERIFY_FLAGS=(--ve ANTHROPIC_API_KEY="$ANTHROPIC_API_KEY")
fi

# --- task list (buildable cells only: task.toml + data + a build definition) --------------
TASKS=()
for d in "$DATASET"/*/; do
  t=$(basename "$d")
  [ -f "$d/task.toml" ] && [ -d "$d/environment/data" ] || continue
  [ -f "$d/environment/Dockerfile" ] || grep -q 'docker_image' "$d/task.toml" 2>/dev/null || continue
  TASKS+=("$t")
done
[ "${#TASKS[@]}" -gt 0 ] || { echo "no buildable tasks in $DATASET" >&2; exit 1; }

# Concurrency-safe cleanup: reap only EXITED containers (never kill another arm's running
# container that shares the task name) and remove a task image only if no container uses it.
cleanup_task() {
  local pfx="${1:0:30}"
  docker ps -aq --filter "name=${pfx}" --filter status=exited 2>/dev/null \
    | xargs -r docker rm -f >/dev/null 2>&1 || true
  for img in $(docker images --format '{{.ID}} {{.Repository}}' 2>/dev/null \
                | awk -v p="$pfx" 'index($2,p)==1{print $1}'); do
    [ -z "$(docker ps -q --filter ancestor="$img" 2>/dev/null)" ] \
      && docker rmi -f "$img" >/dev/null 2>&1 || true
  done
  [ "${BB_PRUNE_BUILDER:-1}" = "1" ] && docker builder prune -f >/dev/null 2>&1 || true
}

# A cell is DONE when it has >= REPLICATES clean deliverables (resume-safe, replicate-aware).
# collect-only -> a real artifacts/answer.txt (>=80 bytes, no 403/429 in trial.log).
# --verify     -> a verifier/reward.json.
is_done() {
  local out="$OUT/$1/$2" n=0 f
  if [ "$VERIFY" = 1 ]; then
    n=$(find "$out" -path '*verifier*' -name reward.json 2>/dev/null | wc -l | tr -d ' ')
    [ "$n" -ge "$REPLICATES" ]; return
  fi
  # collect-only: reject the whole cell if any trial hit a hard rate-limit, else count clean answers
  find "$out" -name trial.log -exec grep -qlE '429 Too Many|403 Forbidden' {} + 2>/dev/null && return 1
  while IFS= read -r f; do
    [ "$(wc -c <"$f" 2>/dev/null)" -ge 80 ] && n=$((n + 1))
  done < <(find "$out" -path '*artifacts*' -name answer.txt 2>/dev/null)
  [ "$n" -ge "$REPLICATES" ]
}

# One harbor invocation for a cell: builds the image once, runs the agent --replicates times.
run_harbor() {
  local agent="$1" task="$2" path="$DATASET/$2" out="$OUT/$1/$2" log="/tmp/run_${1}_${2}.log"
  local -a cmd eff=()
  if [ "$MAX_EFFORT" = 1 ]; then          # per-agent max reasoning (Harbor --ak agent kwargs)
    case "$agent" in
      codex)           eff=(--ak reasoning_effort=xhigh) ;;                      # codex max (gpt-5.5: low<med<high<xhigh)
      claude-code)     eff=(--ak reasoning_effort=max --ak thinking=enabled) ;;  # Opus max + thinking
      antigravity-cli) eff=(--ak "agy_model_display=Gemini 3.1 Pro (High)") ;;   # force High model
    esac
  fi
  case "$agent" in
    codex) cmd=(env -u ANTHROPIC_API_KEY -u OPENAI_API_KEY -u GEMINI_API_KEY CODEX_FORCE_AUTH_JSON=1
        harbor run --yes "${VERIFY_FLAGS[@]}" --path "$path"
        --agent-import-path "$CODEX_AGENT" --model gpt-5.5 "${eff[@]}" -k "$REPLICATES" -n "$REPLICATES" -o "$out") ;;
    claude-code) cmd=(env -u ANTHROPIC_API_KEY -u OPENAI_API_KEY -u GEMINI_API_KEY
        CLAUDE_CODE_OAUTH_TOKEN="${CC_OAUTH_TOKEN:-}"
        harbor run --yes "${VERIFY_FLAGS[@]}" --path "$path"
        --agent claude-code --model claude-opus-4-7 "${eff[@]}" -k "$REPLICATES" -n "$REPLICATES" -o "$out") ;;
    antigravity-cli) cmd=(env -u ANTHROPIC_API_KEY -u OPENAI_API_KEY -u GEMINI_API_KEY -u GOOGLE_API_KEY
        AGY_FORCE_OAUTH=1 AGY_TOKEN_STORE="$AGY_STORE"
        harbor run --yes "${VERIFY_FLAGS[@]}" --path "$path"
        --agent-import-path "$AGY_AGENT" --model gemini/gemini-3.1-pro-preview "${eff[@]}" -k "$REPLICATES" -n "$REPLICATES" -o "$out") ;;
    gemini-cli) cmd=(env -u ANTHROPIC_API_KEY -u OPENAI_API_KEY -u GEMINI_API_KEY GEMINI_FORCE_OAUTH=1
        harbor run --yes "${VERIFY_FLAGS[@]}" --path "$path"
        --agent gemini-cli --model gemini/gemini-3.1-pro-preview -k "$REPLICATES" -n "$REPLICATES" -o "$out") ;;
    *) echo "unknown agent: $agent" >&2; return 9 ;;
  esac
  if [ -n "${BB_DRY_RUN:-}" ]; then               # print the command (secrets redacted), don't run
    printf '%q ' "${cmd[@]}" \
      | sed -E 's/(CLAUDE_CODE_OAUTH_TOKEN=)[^ ]*/\1<redacted>/g; s/(ANTHROPIC_API_KEY=)[^ ]*/\1<redacted>/g'
    echo; return 0
  fi
  rm -rf "$out"; mkdir -p "$out"                           # fresh dir (avoid stale result.json)
  "${cmd[@]}" >>"$log" 2>&1
  cleanup_task "$task"
  is_done "$agent" "$task"                                  # 0 = clean/complete, 1 = failed
}

mode=$([ "$VERIFY" = 1 ] && echo verified || echo collect-only)
echo "run matrix [$mode]: agents=[${AGENTS[*]}] tasks=${#TASKS[@]} reps=$REPLICATES dataset=$DATASET out=$OUT pace=${PACE_SEC}s"
[ "$INITIAL_COOLDOWN" -gt 0 ] && { echo "=== initial cooldown ${INITIAL_COOLDOWN}s $(date +%H:%M:%S) ==="; sleep "$INITIAL_COOLDOWN"; }

for agent in "${AGENTS[@]}"; do
  n=0
  for task in "${TASKS[@]}"; do
    if is_done "$agent" "$task"; then echo "SKIP $agent/$task (done)"; continue; fi
    ok=0
    for attempt in $(seq 1 "$RETRIES"); do
      echo "=== $agent $task (try $attempt) $(date +%H:%M:%S) ==="
      if run_harbor "$agent" "$task"; then echo "    ok $agent/$task $(date +%H:%M:%S)"; ok=1; break; fi
      [ "$attempt" -lt "$RETRIES" ] && { echo "    failed $agent/$task — cooldown ${BACKOFF_SEC}s"; sleep "$BACKOFF_SEC"; }
    done
    [ "$ok" = 0 ] && echo "    GAVE UP $agent/$task after $RETRIES tries"
    n=$((n + 1))
    if [ "$BATCH_COOLDOWN" -gt 0 ] && [ $((n % BATCH)) -eq 0 ]; then
      echo "=== batch cooldown ${BATCH_COOLDOWN}s after $n cells $(date +%H:%M:%S) ==="; sleep "$BATCH_COOLDOWN"
    elif [ "$PACE_SEC" -gt 0 ]; then sleep "$PACE_SEC"; fi
  done
done
echo "RUN MATRIX COMPLETE $(date +%H:%M:%S)"
