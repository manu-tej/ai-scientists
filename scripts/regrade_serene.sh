#!/usr/bin/env bash
# Re-grade or re-run benchmark tasks on a remote Docker host, then judge with a neutral LLM.
#
# Generalises the BiomniBench-DA defect-remediation loop (2026-06-13) so it is reusable for any
# dataset that uses this harness (bench/assemble.py + bench/run.sh + scripts/grade_reps.py).
#
# TWO MODES — pick by what the fix changed:
#   --mode regrade   the RUBRIC changed (agent's existing answer still valid) -> just re-judge
#                    the existing traces under --traces-root. Cheap; no agent compute.
#   --mode rerun     the INSTRUCTION changed (the answer itself is now stale) -> assemble the
#                    fixed tasks, run the agents, then judge. Heavy; needs Docker + agent auth.
#
# HARD-WON GOTCHAS baked in (these cost a day to learn):
#   * Run agents as PARALLEL ARMS (one bench/run.sh per agent). cc/agy/codex are separate
#     accounts; bench/run.sh's docker cleanup is concurrency-safe. ~3x faster than one sequential run.
#   * grade_reps.py judges ALL reps with a usable trace when --prev is omitted (it only skips the
#     resolve_cell-picked rep when reusing a prior single-rep grade). So we omit --prev here.
#   * A rep that wrote answer.txt but NO trace.md is ungradeable (rubric scores the trace) and is
#     silently skipped -> a cell can end up graded over <3 reps. The script reports n_reps so you see it.
#   * codex subscription auth on the remote DIES every ~10 days (single-use refresh-token rotation).
#     If codex fast-fails ("GAVE UP" in ~40s, 401 "refresh token already used"), mirror a FRESH local
#     token:  rsync -a ~/.codex/auth.json <host>:.codex/auth.json   (a valid access token avoids the
#     rotation conflict because the remote then never needs to refresh during the run).
#   * BB_PRUNE_BUILDER=0 on a big host (serene); =1 only on a disk-constrained VM.
#
# USAGE
#   scripts/regrade_serene.sh --mode rerun  --tasks "da-26-2 da-20-4" \
#       --agents "codex claude-code antigravity-cli" --data-root data/biomnibench-da \
#       --host serene --remote benchbench --judge openrouter:minimax/minimax-m3 \
#       --replicates 3 --out runs/regrade_full
#
#   scripts/regrade_serene.sh --mode regrade --tasks "da-15-8 da-4-6" --agents antigravity-cli \
#       --data-root data/biomnibench-da --host serene --remote benchbench \
#       --judge openrouter:minimax/minimax-m3 --traces-root runs/cap3 --out runs/regrade_rubric
#
#   add --dry-run to print the remote commands without executing.
set -uo pipefail

# --- defaults / args ---------------------------------------------------------------------
MODE="" TASKS="" AGENTS="codex claude-code antigravity-cli"
DATA_ROOT="data/biomnibench-da" HOST="serene" REMOTE="benchbench"
JUDGE="openrouter:minimax/minimax-m3" REPLICATES=3
OUT="runs/regrade" TRACES_ROOT="" ASSEMBLE_ARGS="--base"
GRADE_SCRIPT="scripts/grade_reps.py" DRY=0
while [ $# -gt 0 ]; do case "$1" in
  --mode) MODE="$2"; shift 2;;
  --tasks) TASKS="$2"; shift 2;;
  --agents) AGENTS="$2"; shift 2;;
  --data-root) DATA_ROOT="$2"; shift 2;;
  --host) HOST="$2"; shift 2;;
  --remote) REMOTE="$2"; shift 2;;            # remote repo dir, relative to remote $HOME
  --judge) JUDGE="$2"; shift 2;;
  --replicates) REPLICATES="$2"; shift 2;;
  --out) OUT="$2"; shift 2;;
  --traces-root) TRACES_ROOT="$2"; shift 2;;  # regrade mode: where existing per-agent traces live
  --assemble-args) ASSEMBLE_ARGS="$2"; shift 2;;
  --grade-script) GRADE_SCRIPT="$2"; shift 2;;
  --dry-run) DRY=1; shift;;
  -h|--help) sed -n '2,46p' "$0"; exit 0;;
  *) echo "unknown arg: $1" >&2; exit 2;;
esac; done
[ "$MODE" = regrade ] || [ "$MODE" = rerun ] || { echo "need --mode regrade|rerun" >&2; exit 2; }
[ -n "$TASKS" ] || { echo "need --tasks" >&2; exit 2; }
[ "$MODE" = regrade ] && [ -z "$TRACES_ROOT" ] && { echo "regrade needs --traces-root" >&2; exit 2; }

rsh() { if [ "$DRY" = 1 ]; then echo "[dry-run on $HOST] $*"; else ssh -o ConnectTimeout=20 "$HOST" "$*"; fi; }

# --- 0. sync the fixed task files (rubrics/instructions) for these tasks to the host ------
echo "== sync fixed $DATA_ROOT files for [$TASKS] -> $HOST:$REMOTE =="
for t in $TASKS; do
  if [ "$DRY" = 1 ]; then echo "[dry-run] rsync -a $DATA_ROOT/$t/ $HOST:$REMOTE/$DATA_ROOT/$t/"
  else rsync -a "$DATA_ROOT/$t/instruction.md" "$DATA_ROOT/$t/tests/" "$HOST:$REMOTE/$DATA_ROOT/$t/" 2>/dev/null \
         && echo "  synced $t" || echo "  (sync $t partial/failed — check paths)"; fi
done

# --- 1. RERUN: assemble + launch parallel arms + wait ------------------------------------
if [ "$MODE" = rerun ]; then
  echo "== assemble [$TASKS] on $HOST =="
  for t in $TASKS; do
    rsh "cd ~/$REMOTE && export PATH=\$HOME/.local/bin:\$PATH && uv run python -m bench.assemble $ASSEMBLE_ARGS --task $t --out $OUT/_tasks 2>&1 | tail -1"
  done
  echo "== launch one parallel arm per agent (BB_PRUNE_BUILDER=0) =="
  for a in $AGENTS; do
    rsh "cd ~/$REMOTE && nohup bash -lc 'cd ~/$REMOTE && export PATH=\$HOME/.local/bin:\$PATH && BB_PRUNE_BUILDER=0 bench/run.sh --dataset $OUT/_tasks --agents $a --replicates $REPLICATES --out $OUT' </dev/null > $OUT.$a.log 2>&1 & echo launched $a"
  done
  [ "$DRY" = 1 ] && { echo "(dry-run: skipping wait/grade)"; exit 0; }
  echo "== wait for all arms (RUN MATRIX COMPLETE) =="
  for i in $(seq 1 80); do
    n=$(ssh -o ConnectTimeout=10 "$HOST" "grep -l 'RUN MATRIX COMPLETE' $(for a in $AGENTS; do printf '%s ' "$OUT.$a.log"; done) 2>/dev/null | wc -l" 2>/dev/null)
    na=$(echo $AGENTS | wc -w | tr -d ' ')
    echo "  [$i] $n/$na arms complete"; [ "$n" = "$na" ] && break; sleep 90
  done
fi

# --- 2. GRADE (both modes): grade_reps over all reps remotely, then fetch + report LOCALLY -
# (grading runs on the host; parsing happens locally so there is no fragile python-in-ssh.)
GRADE_SRC="$OUT"; [ "$MODE" = regrade ] && GRADE_SRC="$TRACES_ROOT"
echo "== grade with $JUDGE =="
for a in $AGENTS; do
  rsh "cd ~/$REMOTE && export PATH=\$HOME/.local/bin:\$PATH && uv run --env-file .env python $GRADE_SCRIPT --root $GRADE_SRC/$a --data-root $DATA_ROOT --model $JUDGE --out $OUT.grade.$a.json --width 4"
  [ "$DRY" = 1 ] && continue
  scp -q "$HOST:$REMOTE/$OUT.grade.$a.json" "/tmp/regrade_grade_$a.json" 2>/dev/null || { echo "  (could not fetch $a grade json)"; continue; }
  AGENT="$a" TASKS="$TASKS" python3 - <<'PY'
import json, os
a=os.environ["AGENT"]; want=set(os.environ["TASKS"].split())
for d in json.load(open(f"/tmp/regrade_grade_{a}.json")):
    if d["task"] in want:
        print(f"  {a}/{d['task']}: median {d['median']}  n_reps {d['n_reps']}  {d['norms']}")
PY
done
echo
echo "Graded JSONs: $HOST:$REMOTE/$OUT.grade.<agent>.json  (also fetched to /tmp/regrade_grade_<agent>.json)"
echo "Next: write a patch manifest pointing 'source' at those JSONs, then"
echo "      python scripts/patch_grades.py --manifest <patch.json>   to update the score of record."
