#!/bin/bash
# CPU relief diagnostics — what's heavy, what docker is running, what's stale.
echo "=== LOAD / STEAL ==="
uptime
top -bn1 | grep '%Cpu'
echo
echo "=== TOP 12 by MEM ==="
ps -eo pid,user,%cpu,%mem,etime,comm --sort=-%mem | head -13
echo
echo "=== CHROMIUM/BROWSER procs (count + mem) ==="
ps -eo pid,%mem,comm | grep -iE 'chrom|brave|playwright|puppeteer' | grep -v grep | head -20
echo "chromium proc count: $(pgrep -c -f chrom 2>/dev/null)"
echo
echo "=== DOCKER (trader) ==="
docker ps --format '{{.Names}} | {{.Image}} | {{.Status}}' 2>/dev/null || echo "no docker access as trader user"
echo
echo "=== STRAY backtest/sweep procs (ours) ==="
ps -eo pid,etime,args | grep -iE 'wr_sweep|bt_improve|bt_sweep|bt_confirm|backtest_board|asia_desk.backtest' | grep -v grep | head
echo
echo "=== agent state-file freshness (age sec) ==="
cd /home/trader/mt5-bot 2>/dev/null
for f in logs/_orchestrator_state.json logs/asia_desk/_agent_state.json logs/iconic/_agent_state.json logs/jtcc/_jtcc_state.json; do
  if [ -f "$f" ]; then echo "  $(( $(date +%s) - $(stat -c %Y "$f") ))s  $f"; fi
done
