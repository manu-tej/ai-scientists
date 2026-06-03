#!/usr/bin/env bash
# One snapshot of the baseline-capability run, for `watch`.
#   watch -n 1 -c bash ~/benchbench/scripts/watch_baseline.sh
# Per arm: current task, replicates running NOW (this arm), trials finished (3/task at -k3),
# tasks fully done, live/dead. Plus totals, 429 watch, RAM, load.
cd "$(dirname "$0")/.." 2>/dev/null || cd ~/benchbench
OUT="${BB_OUT:-runs/cap3}"
G=$'\e[32m'; R=$'\e[31m'; Y=$'\e[33m'; C=$'\e[36m'; D=$'\e[2m'; B=$'\e[1m'; X=$'\e[0m'

# Map each RUNNING task container -> its arm (via the cap3/<agent>/ mount path) and count per arm.
declare -A RUN
while read -r cnt ag; do [ -n "$ag" ] && RUN[$ag]=$cnt; done < <(
  for cid in $(docker ps -q --filter name=-main 2>/dev/null); do
    docker inspect -f '{{range .Mounts}}{{.Source}}{{"\n"}}{{end}}' "$cid" 2>/dev/null \
      | grep -oE "$OUT/(codex|claude-code|antigravity-cli)" | head -1 | sed -E "s#.*/##"
  done | sort | uniq -c
)

printf "%s═══ benchbench baseline  %s  (%s)═══%s\n" "$B" "$(date +%H:%M:%S)" "$OUT" "$X"
printf "%s%-16s %-12s %4s %9s %7s  %s%s\n" "$D" "ARM" "TASK NOW" "RUN" "TRIALS" "TASKS" "STATUS" "$X"

tot=0
for a in codex claude-code antigravity-cli; do
  task=$(grep "=== $a " "/tmp/cap_$a.log" 2>/dev/null | tail -1 | sed -E "s/.*=== $a ([^ ]+).*/\1/")
  n=$(find "$OUT/$a" -path '*artifacts*' -name answer.txt 2>/dev/null | wc -l)
  run=${RUN[$a]:-0}
  if pgrep -f "bench/run.sh.*--agents $a" >/dev/null; then st="${G}live${X}"; else st="${R}DEAD${X}"; fi
  # plain, aligned numeric columns; color only at the line-end (status) so widths stay correct
  printf "%-16s %-12s %s%2d${X}rep %4d${D}/150${X} %3d${D}/50${X}  %b\n" \
         "$a" "${task:-—}" "$C" "$run" "$n" "$((n/3))" "$st"
  tot=$((tot+n))
done

echo "────────────────────────────────────────────────────────────"
c=$(docker ps --format '{{.Names}}' 2>/dev/null | grep -c -- -main)
k=$(grep -lE '429 Too Many|403 Forbidden' /tmp/cap_codex.log /tmp/run_codex_*.log 2>/dev/null | wc -l)
kc="$G"; [ "$k" -gt 0 ] && kc="$R"
mem=$(free -g | awk '/Mem:/{print $7}'); sw=$(free -g | awk '/Swap:/{print $3}'); ld=$(cut -d' ' -f1 /proc/loadavg)
printf "%sTOTAL ${Y}%d${X}${D}/450 trials${X} │ ${G}%d${X} running │ codex-429 ${kc}%d${X} │ RAM %sG avail │ swap %sG/55 │ load %s\n" \
  "$B" "$tot" "$c" "$k" "$mem" "$sw" "$ld"
