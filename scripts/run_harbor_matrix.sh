#!/usr/bin/env bash
# Faithful execution matrix: run BiomniBench's own coding-agent harnesses
# (Phylo's setup) on our gate-validated unanswerable variants, via Harbor.
#
# Subscription auth (zero API keys) per harness — each vendor opts in differently:
#   claude-code    : CLAUDE_CODE_OAUTH_TOKEN (minted by `claude setup-token`; Claude Max)
#   codex          : CODEX_FORCE_AUTH_JSON=1 (injects host ~/.codex/auth.json ChatGPT OAuth)
#   gemini-cli     : GEMINI_FORCE_OAUTH=1 (injects host ~/.gemini OAuth; Google subscription)
#   antigravity-cli: AGY_FORCE_OAUTH=1 via our custom agent (benchmarks.harbor_agents.
#                    antigravity_oauth). Harbor's STOCK antigravity agent is API-key-only
#                    (no OAuth injection on 0.13.0 or main) and targets the stale ~/.agy
#                    path, so we subclass it to inject ~/.gemini/oauth_creds.json at $0.
#
# Verification is disabled (we score traces with our own Haiku refusal_judge);
# Harbor enforces each task's agent.timeout_sec, so DO NOT wrap in a shell timeout.
#
# Usage: scripts/run_harbor_matrix.sh [K]      (K reruns per cell, default 1)
set -uo pipefail
cd "$(dirname "$0")/.."
set -a; . ./.env; set +a            # load CC_OAUTH_TOKEN etc.
K="${1:-1}"
OUT="runs/harbor_matrix"
# Repo root on PYTHONPATH so Harbor's interpreter can import our custom agent
# (--agent-import-path benchmarks.harbor_agents.antigravity_oauth:AntigravityCliOAuth).
export PYTHONPATH="$PWD${PYTHONPATH:+:$PYTHONPATH}"
AGY_AGENT="benchmarks.harbor_agents.antigravity_oauth:AntigravityCliOAuth"
TASKS=(da-20-1_drop_cell_line da-20-1_single_cell_type da-5-1_drop_pdac
       da-12-4_tiny_n da-12-4_drop_survival da-5-1_drop_tier
       da-13-3_drop_pvalues da-13-3_drop_pct_fat da-17-1_drop_disease)
HEAVY="da-17-1_drop_disease"        # 16 GB container — never run concurrently

run_one() {
  local agent="$1" task="$2" path="runs/harbor_tasks/$2"
  case "$agent" in
    claude-code) env -u ANTHROPIC_API_KEY -u OPENAI_API_KEY -u GEMINI_API_KEY \
        CLAUDE_CODE_OAUTH_TOKEN="$CC_OAUTH_TOKEN" \
        harbor run --path "$path" --agent claude-code --model claude-opus-4-7 \
        --disable-verification -n 1 -o "$OUT" >>"/tmp/hm_${agent}_${task}.log" 2>&1 ;;
    codex) env -u ANTHROPIC_API_KEY -u OPENAI_API_KEY -u GEMINI_API_KEY \
        CODEX_FORCE_AUTH_JSON=1 \
        harbor run --path "$path" --agent codex --model gpt-5.5 \
        --disable-verification -n 1 -o "$OUT" >>"/tmp/hm_${agent}_${task}.log" 2>&1 ;;
    gemini-cli) env -u ANTHROPIC_API_KEY -u OPENAI_API_KEY -u GEMINI_API_KEY GEMINI_FORCE_OAUTH=1 \
        harbor run --path "$path" --agent gemini-cli --model gemini/gemini-3.1-pro-preview \
        --disable-verification -n 1 -o "$OUT" >>"/tmp/hm_${agent}_${task}.log" 2>&1 ;;
    antigravity-cli) env -u ANTHROPIC_API_KEY -u OPENAI_API_KEY -u GEMINI_API_KEY -u GOOGLE_API_KEY \
        AGY_FORCE_OAUTH=1 AGY_TOKEN_STORE="$PWD/runs/harbor_auth/agy_token_store.tgz" \
        harbor run --path "$path" --agent-import-path "$AGY_AGENT" --model gemini/gemini-3.1-pro-preview \
        --disable-verification -n 1 -o "$OUT" >>"/tmp/hm_${agent}_${task}.log" 2>&1 ;;
  esac
}
export -f run_one; export OUT CC_OAUTH_TOKEN AGY_AGENT

for agent in claude-code codex gemini-cli antigravity-cli; do
  for k in $(seq 1 "$K"); do
    # light tasks: 2 concurrent; heavy h5ad task: alone
    printf '%s\n' "${TASKS[@]}" | grep -v "$HEAVY" \
      | xargs -P 2 -I{} bash -c 'run_one "$0" "$1"' "$agent" {}
    run_one "$agent" "$HEAVY"
  done
done
echo "HARBOR MATRIX COMPLETE (agents x ${#TASKS[@]} tasks x K=$K)"
