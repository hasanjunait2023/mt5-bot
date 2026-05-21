"""Quick time audit — Python UTC vs MT5 ticks vs BD time vs sessions."""

from datetime import datetime, timezone, timedelta
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import MetaTrader5 as mt5

mt5.initialize()

py_utc = datetime.now(timezone.utc)
py_bd  = py_utc + timedelta(hours=6)

print("=" * 56)
print("TIME AUDIT")
print("=" * 56)
print(f"Python UTC now  : {py_utc.strftime('%Y-%m-%d %H:%M:%S')}")
print(f"Python BD  now  : {py_bd.strftime('%Y-%m-%d %H:%M:%S')} (UTC+6)")
print()

print("--- Tick freshness per symbol ---")
for sym in ["EURUSD", "GBPUSD", "USDJPY", "XAUUSD", "BTCUSD", "USOIL"]:
    t = mt5.symbol_info_tick(sym)
    if not t:
        print(f"  {sym:<8} no tick")
        continue
    tick_dt = datetime.fromtimestamp(t.time, tz=timezone.utc)
    delta = (py_utc - tick_dt).total_seconds()
    state = "LIVE" if delta < 30 else f"STALE {delta:.0f}s ago"
    print(f"  {sym:<8} {tick_dt.strftime('%H:%M:%S')} UTC  {state}")
print()

# MT5 server time clue: account info
acc = mt5.account_info()
if acc:
    print(f"Broker server   : {acc.server}")
print()

# Session table — UTC / BD side by side
from trading_agents.alpha_desk.sessions import current_session, SESSIONS
print("--- Sessions ---")
print(f"Detected now    : {current_session()}")
print(f"{'name':<8} {'UTC start':<10} {'UTC end':<10} {'BD start':<10} {'BD end'}")
for name, info in SESSIONS.items():
    sh, eh = info.starts_at_utc.hour, info.ends_at_utc.hour
    print(f"{name:<8} {info.starts_at_utc.strftime('%H:%M'):<10} "
          f"{info.ends_at_utc.strftime('%H:%M'):<10} "
          f"{((sh + 6) % 24):02d}:00     {((eh + 6) % 24):02d}:00")
print()

# Pre-session brief schedule in BD
print("--- Pre-session briefs (auto-fire) ---")
for name, info in SESSIONS.items():
    brief_utc_h = (info.starts_at_utc.hour - 0)        # 30 min before
    brief_utc_m = info.starts_at_utc.minute - 30
    if brief_utc_m < 0:
        brief_utc_h -= 1
        brief_utc_m += 60
    brief_bd_h = (brief_utc_h + 6) % 24
    print(f"  {name:<8} {brief_utc_h:02d}:{brief_utc_m:02d} UTC  =  "
          f"{brief_bd_h:02d}:{brief_utc_m:02d} BD")

mt5.shutdown()
