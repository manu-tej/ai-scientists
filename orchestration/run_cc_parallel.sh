#!/usr/bin/env bash
# claude-code full-50 baseline, SIZE-AWARE PARALLEL.
#
# Empirically the Claude Max session cap has NOT bitten (11+ cells clean), so we
# parallelize. Constraint is disk/build pressure on the few huge tasks, NOT the
# token cap. Strategy: light tasks (data < HEAVY_MB) run PAR-wide; the handful of
# huge single-cell tasks run SOLO so two ~18GB builds never collide.
#
# Idempotent: skips cells with a real verifier reward; purges session-limited
# cells (no answer.txt -> verifier 0) before+after so they retry on re-run.
set -uo pipefail
cd "$HOME/benchbench"
export PATH="$HOME/.local/bin:$PATH"
source ~/.bb_verifier_key
[ -n "${ANTHROPIC_API_KEY:-}" ] || { echo "ANTHROPIC_API_KEY missing"; exit 1; }
[ -f ~/.bb_cc_token ] && source ~/.bb_cc_token

PAR="${PAR:-4}"
HEAVY_MB="${HEAVY_MB:-2000}"     # tasks with data >= this run solo
OUT="runs/harbor_base_matrix/claude-code"
TASKS_DIR="runs/harbor_base_tasks"

scored() { compgen -G "$OUT/$1/*/*/verifier/reward.json" >/dev/null 2>&1; }

purge_session_limited() {
  local n=0 trace ts_dir
  while IFS= read -r trace; do
    [ -z "$trace" ] && continue
    if grep -q "session limit" "$trace" 2>/dev/null; then
      ts_dir=$(dirname "$(dirname "$(dirname "$trace")")")
      rm -rf "$ts_dir"; n=$((n+1))
    fi
  done < <(find "$OUT" -name claude-code.txt 2>/dev/null)
  echo "purged $n session-limited cell(s)"
}

run_one() {
  local task="$1" path="$TASKS_DIR/$1" out="$OUT/$1"
  if compgen -G "$out/*/*/verifier/reward.json" >/dev/null 2>&1; then
    echo "SKIP $task (scored)"; return 0
  fi
  mkdir -p "$out"
  echo "START $task $(date +%H:%M:%S)"
  # strip ANTHROPIC_API_KEY from agent env (subscription -> apiKeySource none);
  # key reaches ONLY the verifier via --ve. VKEY is exported by the caller.
  env -u ANTHROPIC_API_KEY -u OPENAI_API_KEY -u GEMINI_API_KEY \
      CLAUDE_CODE_OAUTH_TOKEN="${CC_OAUTH_TOKEN:-}" \
      harbor run --yes --ve ANTHROPIC_API_KEY="$VKEY" \
      --path "$path" --agent claude-code --model claude-opus-4-7 \
      -n 1 -o "$out" >>"/tmp/ccp_${task}.log" 2>&1
  echo "DONE  $task $(date +%H:%M:%S)"
}
# VKEY carries the verifier key into run_one's stripped env (passed via --ve only).
VKEY="$ANTHROPIC_API_KEY"
export -f run_one scored; export OUT TASKS_DIR VKEY CC_OAUTH_TOKEN

# classify unscored tasks into light vs heavy by data size
LIGHT=(); HEAVY=()
for d in "$TASKS_DIR"/*/; do
  t=$(basename "$d")
  scored "$t" && continue
  szm=$(du -sm "$d/environment/data" 2>/dev/null | cut -f1)
  if [ "${szm:-0}" -ge "$HEAVY_MB" ]; then HEAVY+=("$t"); else LIGHT+=("$t"); fi
done

echo "=== pre-purge ==="; purge_session_limited
echo "LIGHT (${#LIGHT[@]}, PAR=$PAR): ${LIGHT[*]}"
echo "HEAVY (${#HEAVY[@]}, solo): ${HEAVY[*]}"

echo "=== light pool, $PAR-wide ==="
printf '%s\n' "${LIGHT[@]}" | xargs -P "$PAR" -I{} bash -c 'run_one "$@"' _ {}

echo "=== heavy tasks, solo ==="
for t in "${HEAVY[@]}"; do run_one "$t"; done

echo "=== post-purge ==="; purge_session_limited
echo "CC PARALLEL DONE: $(find "$OUT" -path '*verifier/reward.json' 2>/dev/null | wc -l)/50 scored"
