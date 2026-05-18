from mt5_bridge import connect, disconnect
from backtest import run

connect()
result = run('BTCUSD', months=1)
m = result.get('metrics', {})

print()
print('=== BTCUSD BASELINE ===')
print(f'Trades:        {m.get("total_trades")}')
print(f'Win Rate:      {m.get("win_rate_pct")}%')
print(f'Profit Factor: {m.get("profit_factor")}')
print(f'Net PnL:       ${m.get("net_pnl")}')
print(f'Max Drawdown:  {m.get("max_drawdown_pct")}%')
print(f'Sharpe:        {m.get("sharpe_ratio")}')
print(f'Final Balance: ${m.get("final_balance")}')

ss = m.get('session_stats', {})
print()
print('Hour-by-hour WR (UTC):')
for h in sorted(ss.keys()):
    d = ss[h]
    bar = '#' * int(d['wr'] / 5)
    print(f'  {h:02d}:00  {d["trades"]:4d} trades  WR {d["wr"]:5.1f}%  {bar}')

disconnect()
