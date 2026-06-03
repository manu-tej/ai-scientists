#!/usr/bin/env bash
# Capability-baseline arm: run UNMODIFIED BiomniBench-DA base tasks. Agent = subscription
# auth ($0). Per-(agent,task) output dir (collision-safe, idempotent skip). Sequential
# within agent to respect Claude session limits.
#
# Two modes:
#   default          : run agent + BiomniBench's real verifier (llm_judge.py, claude-haiku-4-5
#                      via --ve ANTHROPIC_API_KEY; key reaches only the verifier). Scored now.
#   BB_NO_VERIFY=1   : COLLECT-ONLY — run the agent, save traces (answer.txt/trace.md/
#                      transcript), NO verifier, NO API at all during the run. Grade the
#                      saved traces later (e.g. Gemini 3.1 Pro judge via scripts/judge.py).
#
# Usage: run_base_matrix.sh [agent...]                    # verified
#        BB_NO_VERIFY=1 run_base_matrix.sh antigravity-cli # collect traces, grade later
set -uo pipefail
cd "$HOME/benchbench"
export PATH="$HOME/.local/bin:$PATH"
# Repo root on PYTHONPATH so Harbor's interpreter can import our custom agy agent.
export PYTHONPATH="$PWD${PYTHONPATH:+:$PYTHONPATH}"
AGY_AGENT="benchmarks.harbor_agents.antigravity_oauth:AntigravityCliOAuth"
AGY_STORE="$PWD/runs/harbor_auth/agy_token_store.tgz"   # captured Linux subscription token
[ -f ~/.bb_cc_token ] && source ~/.bb_cc_token          # CC_OAUTH_TOKEN if present

NOVERIFY="${BB_NO_VERIFY:-0}"
if [ "$NOVERIFY" = "1" ]; then
  VERIFY_FLAGS=(--disable-verification)
  MODE="collect-only (no verifier; grade traces later)"
else
  source ~/.bb_verifier_key   # exports ANTHROPIC_API_KEY for the verifier
  [ -n "${ANTHROPIC_API_KEY:-}" ] || { echo "ANTHROPIC_API_KEY missing"; exit 1; }
  VERIFY_FLAGS=(--ve ANTHROPIC_API_KEY="$ANTHROPIC_API_KEY")
  MODE="verified (BiomniBench llm_judge.py / claude-haiku-4-5)"
fi

AGENTS=("${@:-codex}")
OUT="runs/harbor_base_matrix"
# Task tree (override to run an isolated affordance tree without disturbing another arm,
# e.g. BB_TASKS_DIR=runs/harbor_base_aff for the codex false-refusal control).
TASKS_DIR="${BB_TASKS_DIR:-runs/harbor_base_tasks}"
TASKS=()
for d in "$TASKS_DIR"/*/; do
  t=$(basename "$d")
  [ -f "$d/task.toml" ] && [ -d "$d/environment/data" ] && TASKS+=("$t")
done

run_one() {
  local agent="$1" task="$2" path="$TASKS_DIR/$2"
  local out="$OUT/${agent}/${task}"
  if [ "$NOVERIFY" = "1" ]; then
    # collect-only: skip if the agent already produced a result for this cell
    if compgen -G "$out/*/result.json" >/dev/null 2>&1; then
      echo "SKIP $agent/$task (trace already collected)"; return 0
    fi
  elif compgen -G "$out/*/*/verifier/reward.json" >/dev/null 2>&1 || compgen -G "$out/*/verifier/reward.json" >/dev/null 2>&1; then
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
        harbor run --yes "${VERIFY_FLAGS[@]}" \
        --path "$path" --agent codex --model gpt-5.5 \
        -n 1 -o "$out" >>"/tmp/base_${agent}_${task}.log" 2>&1 ;;
    claude-code) env -u ANTHROPIC_API_KEY -u OPENAI_API_KEY -u GEMINI_API_KEY \
        CLAUDE_CODE_OAUTH_TOKEN="${CC_OAUTH_TOKEN:-}" \
        harbor run --yes "${VERIFY_FLAGS[@]}" \
        --path "$path" --agent claude-code --model claude-opus-4-7 \
        -n 1 -o "$out" >>"/tmp/base_${agent}_${task}.log" 2>&1 ;;
    antigravity-cli) env -u ANTHROPIC_API_KEY -u OPENAI_API_KEY -u GEMINI_API_KEY -u GOOGLE_API_KEY \
        AGY_FORCE_OAUTH=1 AGY_TOKEN_STORE="$AGY_STORE" \
        harbor run --yes "${VERIFY_FLAGS[@]}" \
        --path "$path" --agent-import-path "$AGY_AGENT" --model gemini/gemini-3.1-pro-preview \
        -n 1 -o "$out" >>"/tmp/base_${agent}_${task}.log" 2>&1 ;;
  esac
  echo "    done $agent $task $(date +%H:%M:%S)"
}

echo "base matrix [$MODE]: agents=[${AGENTS[*]}] tasks=[${TASKS[*]}]"
for agent in "${AGENTS[@]}"; do
  for task in "${TASKS[@]}"; do
    run_one "$agent" "$task"
  done
done
echo "BASE MATRIX COMPLETE"
