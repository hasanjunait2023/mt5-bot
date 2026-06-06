"""Iconic board WR sweep — load board once, sweep BOARD_SCORE_MIN over a large
full-range IS/OOS split (bigger sample than the fixed 2500/1500 walkforward).
Goal: find a score floor that robustly raises WR + expectancy on BOTH IS and OOS.

    MT5_BRIDGE_URL=http://localhost:8090 python -m trading_agents.iconic.wr_sweep --limit 10000
"""
import argparse
from trading_agents.iconic import backtest_board as bb

SCORE_MINS = [0, 50, 60, 65, 70, 75, 80]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=10000)
    args = ap.parse_args()

    data, _ = bb._load_board(args.limit, with_m15=False)
    if len(data) < 10:
        print("not enough pairs"); return
    n = min(len(df) for df in data.values())
    cut = int(n * 0.6)
    print(f"\n{'='*92}\nICONIC BOARD WR SWEEP — {len(data)} pairs, {n} H1 bars | IS[{bb.WARMUP},{cut}) OOS[{cut},{n})\n{'='*92}")
    print(f"{'score>=':>8} | {'IS: n  WR    PF   expR  win/loss':38s} | {'OOS: n  WR    PF   expR  win/loss'}")

    def fmt(r):
        return (f"n={r['trades']:3d} WR{r['win_rate']:5.1f} PF{r['profit_factor_R']:5.2f} "
                f"E{r['expectancy_R']:+.2f} {r['avg_win_R']:+.2f}/{r['avg_loss_R']:+.2f}")

    base_is = base_oos = None
    for sm in SCORE_MINS:
        bb.SCORE_MIN = float(sm)
        is_r = bb._simulate(data, bb.WARMUP, cut)
        oos_r = bb._simulate(data, cut, n)
        if sm == 0:
            base_is, base_oos = is_r, oos_r
        tag = ""
        if sm > 0 and base_is and base_oos:
            better = (is_r["win_rate"] > base_is["win_rate"] and oos_r["win_rate"] > base_oos["win_rate"]
                      and is_r["profit_factor_R"] >= base_is["profit_factor_R"]
                      and oos_r["profit_factor_R"] >= base_oos["profit_factor_R"]
                      and is_r["trades"] >= 15 and oos_r["trades"] >= 10)
            tag = "<< robust WR+PF beat" if better else ""
        print(f"{sm:>8} | {fmt(is_r):38s} | {fmt(oos_r)}  {tag}")


if __name__ == "__main__":
    main()
