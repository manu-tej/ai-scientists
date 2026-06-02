#!/usr/bin/env bash
# Mac cc arm: run claude-code on the 6 locally-available tasks that are DISJOINT
# from serene's live cell (da-1-3). Subscription auth ($0) ONLY — every cell is
# auth-gated: the moment a cell's agent log shows apiKeySource=ANTHROPIC_API_KEY
# (i.e. it would BILL the API key instead of using the Max subscription), the
# whole run aborts and the container is killed. Fails CLOSED: no OAuth -> no run.
set -uo pipefail
cd "$HOME/2026/ai-scientists"
export PATH="$HOME/.local/bin:$PATH"
source ~/.bb_verifier_key                                      # ANTHROPIC_API_KEY (verifier only, via --ve)
[ -n "${ANTHROPIC_API_KEY:-}" ] || { echo "FATAL: no verifier key"; exit 1; }
source ~/.bb_cc_token                                          # CC_OAUTH_TOKEN (agent $0 auth)
[ -n "${CC_OAUTH_TOKEN:-}" ] || { echo "FATAL: no CC oauth token — refusing to run (would risk billing)"; exit 1; }

# da-3-4 first (lightest: Mann-Whitney) for a fast auth signal; da-1-3 EXCLUDED (serene owns it).
TASKS=(da-3-4 da-5-1 da-20-1 da-17-1 da-13-3 da-12-4)
B="runs/harbor_base_matrix/claude-code"

run_cell() {
  local task="$1" path="runs/harbor_base_tasks/$1" out="$B/$1"
  if compgen -G "$out/*/*/verifier/reward.json" >/dev/null 2>&1; then echo "SKIP $task (already scored)"; return 0; fi
  mkdir -p "$out"
  echo "=== cc $task START $(date +%H:%M:%S) ==="
  env -u ANTHROPIC_API_KEY -u OPENAI_API_KEY -u GEMINI_API_KEY \
      CLAUDE_CODE_OAUTH_TOKEN="$CC_OAUTH_TOKEN" \
      harbor run --yes --ve ANTHROPIC_API_KEY="$ANTHROPIC_API_KEY" \
      --path "$path" --agent claude-code --model claude-opus-4-7 \
      -n 1 -o "$out" >>"/tmp/mac_cc_${task}.log" 2>&1 &
  local hpid=$!
  # AUTH GATE — poll the live agent log; abort the whole run on any billing signal.
  local i f
  for i in $(seq 1 90); do            # up to ~7.5 min for the agent log + apiKeySource to appear
    sleep 5
    f=$(find "$out" -name claude-code.txt -newermt "-25 minutes" 2>/dev/null | head -1)
    if [ -n "$f" ] && grep -q "apiKeySource" "$f" 2>/dev/null; then
      if grep -q '"apiKeySource":"ANTHROPIC' "$f"; then
        echo "!!! BILLING DETECTED ($task): apiKeySource=ANTHROPIC_API_KEY — ABORTING RUN !!!"
        kill -9 "$hpid" 2>/dev/null
        pkill -9 -f "agent claude-code" 2>/dev/null
        docker ps --format '{{.Names}}' | grep "${task}__" | xargs -r docker rm -f >/dev/null 2>&1
        exit 9
      fi
      echo "AUTH OK ($task): apiKeySource=none — \$0 subscription. Cell proceeds."
      break
    fi
    kill -0 "$hpid" 2>/dev/null || { echo "  (harbor exited before auth log — check /tmp/mac_cc_${task}.log)"; break; }
  done
  wait "$hpid" 2>/dev/null
  local sc; sc=$(find "$out" -path '*verifier/reward.json' -exec grep -o '[0-9]\+' {} \; 2>/dev/null | head -1)
  echo "=== cc $task DONE $(date +%H:%M:%S) score=${sc:-NONE} ==="
}

for t in "${TASKS[@]}"; do run_cell "$t"; done
echo "MAC CC ARM COMPLETE: $(for d in "$B"/*/; do t=$(basename "$d"); compgen -G "$B/$t"/*/*/verifier/reward.json >/dev/null 2>&1 && echo "$t"; done | tr '\n' ' ')"
