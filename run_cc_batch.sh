#!/usr/bin/env bash
# claude-code full-50 baseline, run in SESSION-LIMITED BATCHES.
#
# claude-code auths via Claude Max (rolling ~5h session cap). A long sequential
# run exhausts it after ~10-15 cells, after which cells fail: the agent phase is
# killed mid-task, no /app/answer.txt is written, and the verifier scores it 0.
# A 0 would poison run_base_matrix.sh's skip-guard (it looks "done"), so this
# wrapper PURGES any cell whose claude-code trace contains the session-limit
# marker BEFORE and AFTER the batch — so the next batch (post-reset) retries it.
#
# Re-run this same script after each ~5h reset; idempotent skip resumes the rest.
set -uo pipefail
cd "$HOME/benchbench"
export PATH="$HOME/.local/bin:$PATH"
BASE="runs/harbor_base_matrix/claude-code"

purge_session_limited() {
  local n=0
  while IFS= read -r trace; do
    [ -z "$trace" ] && continue
    if grep -q "session limit" "$trace" 2>/dev/null; then
      # cell dir = .../claude-code/<task>/<ts>/<cell>/agent/claude-code.txt -> rm the <ts>
      ts_dir=$(dirname "$(dirname "$(dirname "$trace")")")
      echo "  purge session-limited: ${ts_dir#"$BASE"/}"
      rm -rf "$ts_dir"; n=$((n+1))
    fi
  done < <(find "$BASE" -name claude-code.txt 2>/dev/null)
  echo "purged $n session-limited cell(s)"
}

echo "=== pre-batch purge ==="
purge_session_limited
echo "=== run batch (skips already-scored, real-reward cells) ==="
./run_base_matrix.sh claude-code
echo "=== post-batch purge (clean any just-stalled cells) ==="
purge_session_limited

scored=$(find "$BASE" -path "*verifier/reward.json" 2>/dev/null | wc -l)
echo "CC BATCH DONE: $scored / 50 cells have a real score"
