"""
EA Performance Report — realized per-EA stats from live MT5 history.

Pulls closed-trade history from MT5, groups by magic number, and computes
REAL performance (spread + commission + swap included — unlike the backtest):
trades, win rate, profit factor, net P&L, avg win/loss, expectancy, max DD.

Writes mt5_bridge/_ea_performance.json (same bridge→dashboard pattern as
_live_state.json) and prints a console table. Run on the machine with MT5.

Usage:  python ea_performance_report.py [--days 30] [--loop 300]
"""
import sys, json, argparse, time
from pathlib import Path
from datetime import datetime, timedelta, timezone

import MetaTrader5 as mt5

OUT_PATH = Path(__file__).parent / "mt5_bridge" / "_ea_performance.json"

# magic -> (label, group). Keep in sync with the EAs actually deployed.
EA_MAGICS = {
    20260102: ("S1 Swing Scalp",        "FxVault"),
    20260500: ("S5 News Spike Reversal","FxVault"),
    20260602: ("S6 Asian Range",        "FxVault"),
    20260101: ("S2 M5 Scalp",           "FxVault-inspection"),
    20260103: ("S3 M1 HFT Sniper",      "FxVault-inspection"),
    20260104: ("S4 Multi-Pair",         "FxVault-inspection"),
    20260100: ("MTF EMA Scalper M1",    "ScalpMaster"),
    20260516: ("ScalpMaster HFT",       "ScalpMaster"),
    20260517: ("ScalpMaster HFT Aggr.", "ScalpMaster"),
    20260002: ("XAUUSD Gold Scalper",   "ScalpMaster"),
    20260001: ("BTCUSD Scalper",        "ScalpMaster"),
    20260700: ("NextGenSync Grid",      "Inspection (unvalidated)"),
    20260800: ("NextGenSync Pyramid",   "Inspection (unvalidated)"),
    20260900: ("NGS_Range (validated)", "Ready (PF 1.29 GBPUSD)"),
}


def _max_drawdown(pnls):
    """Max peak-to-trough drawdown of the realized equity curve ($)."""
    eq, peak, mdd = 0.0, 0.0, 0.0
    for p in pnls:
        eq += p
        peak = max(peak, eq)
        mdd = min(mdd, eq - peak)      # most negative dip below peak
    return round(abs(mdd), 2)


def _stats(positions):
    """positions: list of dicts {pnl, close_time} for one EA."""
    n = len(positions)
    if n == 0:
        return {"trades": 0}
    positions = sorted(positions, key=lambda x: x["close_time"])
    pnls = [p["pnl"] for p in positions]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    gross_w = sum(wins)
    gross_l = abs(sum(losses))
    net = round(sum(pnls), 2)
    pf = round(gross_w / gross_l, 2) if gross_l > 0 else (999.0 if gross_w > 0 else 0.0)
    return {
        "trades":        n,
        "wins":          len(wins),
        "losses":        len(losses),
        "win_rate":      round(100.0 * len(wins) / n, 1),
        "profit_factor": pf,
        "net_pnl":       net,
        "gross_profit":  round(gross_w, 2),
        "gross_loss":    round(gross_l, 2),
        "avg_win":       round(gross_w / len(wins), 2) if wins else 0.0,
        "avg_loss":      round(gross_l / len(losses), 2) if losses else 0.0,
        "expectancy":    round(net / n, 2),
        "max_drawdown":  _max_drawdown(pnls),
        "last_close":    positions[-1]["close_time"],
    }


def build_report(days: int) -> dict:
    if not mt5.initialize():
        return {"error": f"MT5 init failed: {mt5.last_error()}",
                "generated_at": datetime.now(timezone.utc).isoformat()}

    acct = mt5.account_info()
    frm = datetime.now() - timedelta(days=days)
    deals = mt5.history_deals_get(frm, datetime.now())
    mt5.shutdown()

    # group deals by position_id -> realized net (profit+commission+swap)
    pos_pnl, pos_magic, pos_time, pos_sym = {}, {}, {}, {}
    for d in (deals or []):
        if d.type == mt5.DEAL_TYPE_BALANCE:      # skip deposits/withdrawals
            continue
        pid = d.position_id
        pos_pnl[pid]  = pos_pnl.get(pid, 0.0) + d.profit + d.commission + d.swap
        if d.magic:
            pos_magic[pid] = d.magic
        pos_time[pid] = max(pos_time.get(pid, 0), d.time)
        pos_sym[pid]  = d.symbol

    # bucket closed positions by magic
    by_magic = {}
    for pid, pnl in pos_pnl.items():
        magic = pos_magic.get(pid, 0)
        by_magic.setdefault(magic, []).append(
            {"pnl": round(pnl, 2),
             "close_time": datetime.utcfromtimestamp(pos_time[pid]).isoformat()})

    eas = []
    for magic, plist in sorted(by_magic.items()):
        label, group = EA_MAGICS.get(magic, (f"Magic {magic} (unmapped)", "Unknown"))
        eas.append({"magic": magic, "name": label, "group": group, **_stats(plist)})

    eas.sort(key=lambda e: e.get("net_pnl", 0), reverse=True)
    total_net = round(sum(e.get("net_pnl", 0) for e in eas), 2)
    total_tr  = sum(e.get("trades", 0) for e in eas)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "lookback_days": days,
        "account": {
            "login":   acct.login if acct else None,
            "server":  acct.server if acct else None,
            "balance": round(acct.balance, 2) if acct else None,
            "equity":  round(acct.equity, 2) if acct else None,
            "currency": acct.currency if acct else None,
        },
        "summary": {
            "total_eas":   len(eas),
            "total_trades": total_tr,
            "total_net_pnl": total_net,
        },
        "eas": eas,
        "note": "Realized P&L incl. spread/commission/swap — real (not backtest).",
    }


def write_and_print(rep: dict):
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(rep, indent=2), encoding="utf-8")
    if "error" in rep:
        print("ERROR:", rep["error"]); return
    a = rep["account"]
    print(f"\n  EA PERFORMANCE -- {a['login']} {a['server']} | "
          f"bal ${a['balance']} eq ${a['equity']} | last {rep['lookback_days']}d")
    print("  " + "-" * 86)
    print(f"  {'EA':28} {'Tr':>4} {'WR%':>6} {'PF':>6} "
          f"{'Net$':>10} {'AvgW':>8} {'AvgL':>8} {'MaxDD$':>8}")
    print("  " + "-" * 86)
    if not rep["eas"]:
        print("  (no closed trades yet in window)")
    for e in rep["eas"]:
        if e.get("trades", 0) == 0:
            continue
        print(f"  {e['name'][:28]:28} {e['trades']:>4} {e['win_rate']:>6.1f} "
              f"{e['profit_factor']:>6.2f} {e['net_pnl']:>10.2f} "
              f"{e['avg_win']:>8.2f} {e['avg_loss']:>8.2f} {e['max_drawdown']:>8.2f}")
    print("  " + "-" * 86)
    print(f"  TOTAL net ${rep['summary']['total_net_pnl']} "
          f"over {rep['summary']['total_trades']} trades  ->  {OUT_PATH}")
    print("  recent closes:")
    for e in rep["eas"]:
        if e.get("trades", 0):
            print(f"    {e['name'][:24]:24} last close {e.get('last_close','?')}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--loop", type=int, default=0,
                    help="seconds between refreshes (0 = run once)")
    args = ap.parse_args()
    while True:
        write_and_print(build_report(args.days))
        if args.loop <= 0:
            break
        time.sleep(args.loop)


if __name__ == "__main__":
    main()
