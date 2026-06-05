"""Export the -7..+7 currency-strength H1 timeline to CSV for the MT5 EA.

The MT5 Strategy Tester's local agent can't reliably sync 28 cross-symbols, so
the multi-currency strength is precomputed here (same engine as the live agent)
and written as a CSV the EA reads — then the tester only needs the chart symbol.

Row format (one per H1 close): epoch,USD,EUR,GBP,JPY,AUD,NZD,CAD,CHF

Run where the bridge has history (the VPS), then copy the CSV into the local
MT5 Common\\Files folder:
    python -m trading_agents.scalp.export_strength_csv --out strength_h1.csv
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE_DIR))

import trading_agents.scalp.backtest as bt
from trading_agents.strength.strength import MAJORS


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="strength_h1.csv")
    args = ap.parse_args()

    bt._build_strength_history()
    # Access via the module — _build_strength_history rebinds these globals.
    ts, val = bt._STRENGTH_TS, bt._STRENGTH_VAL
    spine = ts.get("USD", [])
    if not spine:
        print("ERROR: strength history empty (bridge unreachable?)")
        sys.exit(1)

    out = Path(args.out)
    n = len(spine)
    with out.open("w", encoding="ascii") as f:
        f.write("time," + ",".join(MAJORS) + "\n")
        for i in range(n):
            row = [str(int(spine[i]))]
            row += [str(val[c][i]) for c in MAJORS]
            f.write(",".join(row) + "\n")
    print(f"wrote {out} | {n} H1 rows | {spine[0]}..{spine[-1]}")


if __name__ == "__main__":
    main()
