#!/usr/bin/env bash
cd /home/trader/mt5-bot
pkill -u trader -f backtest_board 2>/dev/null
sleep 2
export MT5_BRIDGE_URL=http://localhost:8090
# 15000 H1 bars (~1.7yr) + M15, FULL window (no walk-forward) → max trade count
setsid nohup nice -n 15 .venv/bin/python -m trading_agents.iconic.backtest_board --limit 15000 --m15 \
  > logs/jtcc/_board_bt.log 2>&1 < /dev/null &
echo "launched pid=$!"
