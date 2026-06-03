#!/usr/bin/env bash
# One snapshot of the baseline-capability run, for `watch`.
#   watch -n 1 -c bash ~/benchbench/scripts/watch_baseline.sh
# Per arm: current task, trials finished (3/task at -k3), tasks done, alive/dead.
# Plus: concurrent replicates (containers grouped by task), totals, 429 watch, RAM, load.
cd "$(dirname "$0")/.." 2>/dev/null || cd ~/benchbench
OUT="${BB_OUT:-runs/cap3}"
G=$'\e[32m'; R=$'\e[31m'; Y=$'\e[33m'; D=$'\e[2m'; B=$'\e[1m'; X=$'\e[0m'

printf "%s═══ benchbench baseline  %s  (%s)═══%s\n" "$B" "$(date +%H:%M:%S)" "$OUT" "$X"
printf "%s%-16s %-22s %9s %7s %8s%s\n" "$D" "ARM" "TASK NOW" "TRIALS" "TASKS" "STATUS" "$X"

tot=0
for a in codex claude-code antigravity-cli; do
  task=$(grep "=== $a " "/tmp/cap_$a.log" 2>/dev/null | tail -1 | sed -E "s/.*=== $a ([^ ]+).*/\1/")
  n=$(find "$OUT/$a" -path '*artifacts*' -name answer.txt 2>/dev/null | wc -l)
  if pgrep -f "bench/run.sh.*--agents $a" >/dev/null; then st="${G}live${X}"; else st="${R}DEAD${X}"; fi
  printf "%-16s %-22s %s%4d${D}/150${X} %s%3d${D}/50${X} %8s\n" \
         "$a" "${task:-—}" "$Y" "$n" "$Y" "$((n/3))" "$st"
  tot=$((tot+n))
done

echo "────────────────────────────────────────────────────────────"
printf "%sreplicates running now (containers per task):%s\n" "$D" "$X"
docker ps --format '{{.Names}}' 2>/dev/null | grep -- -main \
  | sed -E 's/__[a-z0-9]+-main-1//' | sort | uniq -c \
  | awk -v g="$G" -v x="$X" '{printf "   %s%d×%s %s\n",g,$1,x,$2}'

c=$(docker ps --format '{{.Names}}' 2>/dev/null | grep -c -- -main)
k=$(grep -lE '429 Too Many|403 Forbidden' /tmp/cap_codex.log /tmp/run_codex_*.log 2>/dev/null | wc -l)
kcol="$G"; [ "$k" -gt 0 ] && kcol="$R"
mem=$(free -g | awk '/Mem:/{print $7}'); sw=$(free -g | awk '/Swap:/{print $3}'); ld=$(cut -d' ' -f1 /proc/loadavg)
printf "%sTOTAL %s%d${X}%s/450 trials │ %sconc %d${X} │ codex-429 %s%d${X} │ RAM %sG avail │ swap %sG/55 │ load %s%s\n" \
  "$B" "$Y" "$tot" "$D" "$G" "$c" "$kcol" "$k" "$mem" "$sw" "$ld" "$X"
