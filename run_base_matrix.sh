#!/usr/bin/env bash
# Capability-baseline arm: run UNMODIFIED BiomniBench-DA base tasks WITH the real
# verifier (BiomniBench llm_judge.py on Claude Haiku). Agent = subscription auth;
# verifier gets ANTHROPIC_API_KEY only. Per-(agent,task) output dir (collision-safe,
# idempotent skip). Sequential within agent to respect Claude session limits.
#
# Usage: run_base_matrix.sh [agent...]   default: codex
set -uo pipefail
cd "$HOME/benchbench"
export PATH="$HOME/.local/bin:$PATH"
source ~/.bb_verifier_key   # exports ANTHROPIC_API_KEY for the verifier
[ -n "${ANTHROPIC_API_KEY:-}" ] || { echo "ANTHROPIC_API_KEY missing"; exit 1; }
[ -f ~/.bb_cc_token ] && source ~/.bb_cc_token   # CC_OAUTH_TOKEN if present

AGENTS=("${@:-codex}")
OUT="runs/harbor_base_matrix"
# only the base tasks that are present + complete on this host
TASKS=()
for d in runs/harbor_base_tasks/*/; do
  t=$(basename "$d")
  [ -f "$d/task.toml" ] && [ -d "$d/environment/data" ] && TASKS+=("$t")
done

run_one() {
  local agent="$1" task="$2" path="runs/harbor_base_tasks/$2"
  local out="$OUT/${agent}/${task}"
  if compgen -G "$out/*/*/verifier/reward.json" >/dev/null 2>&1 || compgen -G "$out/*/verifier/reward.json" >/dev/null 2>&1; then
    echo "SKIP $agent/$task (already scored)"; return 0
  fi
  mkdir -p "$out"
  echo "=== $agent $task $(date +%H:%M:%S) ==="
  # CRITICAL: strip ANTHROPIC_API_KEY from the AGENT env (else claude-code bills
  # the API key instead of using the Max subscription — apiKeySource must be
  # "none"). The verifier's key is injected ONLY via --ve, so it never reaches
  # the agent. codex ignores the Anthropic key anyway, but we strip it there too
  # for symmetry / safety.
  case "$agent" in
    codex) env -u ANTHROPIC_API_KEY -u OPENAI_API_KEY -u GEMINI_API_KEY CODEX_FORCE_AUTH_JSON=1 \
        harbor run --yes --ve ANTHROPIC_API_KEY="$ANTHROPIC_API_KEY" \
        --path "$path" --agent codex --model gpt-5.5 \
        -n 1 -o "$out" >>"/tmp/base_${agent}_${task}.log" 2>&1 ;;
    claude-code) env -u ANTHROPIC_API_KEY -u OPENAI_API_KEY -u GEMINI_API_KEY \
        CLAUDE_CODE_OAUTH_TOKEN="${CC_OAUTH_TOKEN:-}" \
        harbor run --yes --ve ANTHROPIC_API_KEY="$ANTHROPIC_API_KEY" \
        --path "$path" --agent claude-code --model claude-opus-4-7 \
        -n 1 -o "$out" >>"/tmp/base_${agent}_${task}.log" 2>&1 ;;
  esac
  echo "    done $agent $task $(date +%H:%M:%S)"
}

echo "base matrix: agents=[${AGENTS[*]}] tasks=[${TASKS[*]}]"
for agent in "${AGENTS[@]}"; do
  for task in "${TASKS[@]}"; do
    run_one "$agent" "$task"
  done
done
echo "BASE MATRIX COMPLETE"
