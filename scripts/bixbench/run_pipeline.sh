#!/usr/bin/env bash
# Reproduce the BixBench-Verified-50 capability+consistency run end-to-end.
#
# Pipeline:  HF bucket -> build Harbor tasks -> run agents (k reps) -> grade -> merge.
# Designed to run on the Harbor host (where bench/run.sh + the agent CLIs live). The
# grader/merge steps are pure Python and can also run anywhere with the run outputs.
#
# Prereqs:
#   - .env with OPENROUTER_API_KEY (judge) and the agents' subscription OAuth tokens
#     (CC_OAUTH_TOKEN, codex ChatGPT auth, antigravity-cli Google token). NEVER use
#     billable API keys for the agents.
#   - `hf` CLI authenticated (HF_TOKEN) for the capsule download.
#   - bench/run.sh patched to honour BB_MIN_ANSWER_BYTES (BixBench answers are terse;
#     the default 80-byte is_done floor would reject correct short answers). See
#     docs/research/2026-06-04-bixbench-verified-50-integration.md.
#
# Usage:   bash scripts/bixbench/run_pipeline.sh [TASK_IDS...]
#   no args      -> all 50 tasks
#   TASK_IDS...  -> subset (e.g. bix-18-q1 bix-30-q3 ...)
set -euo pipefail

BUCKET="${BB_BUCKET:-hf://buckets/amanutej/benchbench/BixBench-Verified-50}"
WORK="${BB_WORK:-/tmp/bixfull}"            # capsule download dir
TASKS="${BB_TASKS:-runs/bixbench_full}"    # built Harbor task tree
OUT="${BB_OUT:-runs/bixbench_full_out}"    # agent run outputs
AGENTS="${BB_AGENTS:-claude-code codex antigravity-cli}"
REPS="${BB_REPS:-3}"
PY="${BB_PY:-uv run --env-file .env python}"
IDS=("$@")

echo "==> 1. download manifest + capsules from $BUCKET"
mkdir -p "$WORK/caps"
hf buckets cp "$BUCKET/BixBench-Verified-50.jsonl" "$WORK/BixBench-Verified-50.jsonl"
# Only the capsules referenced by the requested ids (all 50 if none given).
mapfile -t NEED < <($PY - "$WORK/BixBench-Verified-50.jsonl" "${IDS[@]}" <<'PY'
import json, sys
recs = [json.loads(l) for l in open(sys.argv[1]) if l.strip()]
want = set(sys.argv[2:])
caps = {r["data_folder"] for r in recs if not want or r["question_id"] in want}
print("\n".join(sorted(caps)))
PY
)
for cap in "${NEED[@]}"; do
  [ -f "$WORK/caps/$cap" ] || hf buckets cp "$BUCKET/$cap" "$WORK/caps/$cap"
done

echo "==> 2. build Harbor tasks (strips the executed notebook; keeps CapsuleData only)"
$PY scripts/build_bixbench_tasks.py \
    --jsonl "$WORK/BixBench-Verified-50.jsonl" --capsules-dir "$WORK/caps" \
    --out "$TASKS" ${IDS[@]:+--ids "${IDS[@]}"}

echo "==> 3. run each agent (k=$REPS reps). is_done skips already-complete tasks (resume)."
for ag in $AGENTS; do
  setsid env BB_PRUNE_BUILDER=0 BB_MAX_EFFORT=1 BB_MIN_ANSWER_BYTES=1 \
    bash bench/run.sh --dataset "$TASKS" --agents "$ag" \
    --replicates "$REPS" --max-effort --out "$OUT" \
    >"/tmp/bixrun_${ag}.log" 2>&1 </dev/null &
  echo "   launched $ag -> /tmp/bixrun_${ag}.log"
done
wait
echo "   all agents finished"

echo "==> 4. grade each agent with the neutral MiniMax-M3 judge"
for ag in $AGENTS; do
  $PY scripts/grade_bixbench.py --tasks "$TASKS" \
      --root "$OUT/$ag" --out "runs/bixbench_full_${ag}_grade.json"
done

echo "==> 5. merge per-agent + cross-agent summary"
$PY scripts/bixbench/merge_grades.py \
    --agent cc    "runs/bixbench_full_claude-code_grade.json" \
    --agent codex "runs/bixbench_full_codex_grade.json" \
    --agent agy   "runs/bixbench_full_antigravity-cli_grade.json" \
    --out runs/bixbench_full50_summary.json
echo "done."
