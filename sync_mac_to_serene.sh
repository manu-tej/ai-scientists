#!/usr/bin/env bash
# Push Mac-completed cc cells to serene so serene's skip-guard skips them
# (avoids both machines running the same cell). Runs while the Mac cc arm is alive.
set -uo pipefail
cd "$HOME/2026/ai-scientists"
H="${SYNC_HOST:-user@host}"
B=runs/harbor_base_matrix/claude-code
while pgrep -f "run_mac_cc.sh" >/dev/null 2>&1; do
  for d in "$B"/*/; do
    t=$(basename "$d")
    compgen -G "$B/$t"/*/*/verifier/reward.json >/dev/null 2>&1 || continue
    # already on serene?
    if ! ssh -o ConnectTimeout=6 $H "compgen -G ~/benchbench/$B/$t/*/*/verifier/reward.json >/dev/null 2>&1"; then
      echo "SYNC $t -> serene"
      rsync -a -e "ssh -o ConnectTimeout=6" "$B/$t/" "$H:~/benchbench/$B/$t/" 2>/dev/null && echo "  synced $t"
    fi
  done
  sleep 180
done
echo "SYNCER EXIT (mac cc arm done)"
