#!/usr/bin/env bash
# Guarantee every base task gets a REAL verifier score for the given agent.
#
# run_base_matrix.sh does a single pass: a cell that errors / hits a session
# limit / hangs is skipped and never retried. This wrapper re-runs passes until
# every discoverable task has a real reward.json, purging poisoned scores between
# passes (session-limited cells score 0 with no answer.txt -> must retry).
#
# Idempotent: completed cells skip instantly, so each pass only does the gaps.
# Bounded: stops after MAX_PASSES to avoid an infinite loop on a truly broken task.
#
# Usage: run_until_complete.sh <agent> [max_passes]
set -uo pipefail
cd "$HOME/benchbench"
export PATH="$HOME/.local/bin:$PATH"
AGENT="${1:?need agent}"
MAX_PASSES="${2:-6}"
B="runs/harbor_base_matrix/$AGENT"
T="runs/harbor_base_tasks"

unscored_list() {
  local u=""
  for d in "$T"/*/; do
    local t; t=$(basename "$d")
    [ -f "$d/task.toml" ] && [ -d "$d/environment/data" ] || continue
    compgen -G "$B/$t"/*/*/verifier/reward.json >/dev/null 2>&1 || u="$u $t"
  done
  echo "$u"
}

purge_poisoned() {
  # remove cells whose agent trace hit the session limit (scored 0, no real attempt)
  local n=0 trace ts
  while IFS= read -r trace; do
    [ -z "$trace" ] && continue
    if grep -q "session limit" "$trace" 2>/dev/null; then
      ts=$(dirname "$(dirname "$(dirname "$trace")")"); rm -rf "$ts"; n=$((n+1))
    fi
  done < <(find "$B" -name "$AGENT.txt" 2>/dev/null)
  [ "$n" -gt 0 ] && echo "  purged $n session-limited cell(s)"
}

pass=0
while [ "$pass" -lt "$MAX_PASSES" ]; do
  purge_poisoned
  remaining=$(unscored_list)
  if [ -z "${remaining// }" ]; then
    echo "ALL TASKS SCORED for $AGENT after $pass pass(es)."
    break
  fi
  pass=$((pass+1))
  echo "=== PASS $pass ($AGENT): $(echo $remaining | wc -w) unscored:$remaining ==="
  ./run_base_matrix.sh "$AGENT"   # single pass; skips already-scored, runs the gaps
done

# final report
final_unscored=$(unscored_list)
scored=$(find "$B" -path '*verifier/reward.json' 2>/dev/null | wc -l)
echo "DONE $AGENT: $scored scored; still-unscored:${final_unscored:-none}"
[ -z "${final_unscored// }" ] || echo "WARN: ${final_unscored} never scored after $MAX_PASSES passes — inspect manually"
