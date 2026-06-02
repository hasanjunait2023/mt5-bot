"""
MT5 Bridge — connects to running MetaTrader5 terminal and fetches data.
Usage:
    python mt5_bridge.py                   # connection test
    python mt5_bridge.py --symbol XAUUSD   # fetch + show data info
"""

import sys
import argparse
import time
from datetime import datetime, timedelta

import bridge_client as mt5   # HTTP-bridge shim (sibling import). Legacy data layer (fetch_ohlcv/get_pip_size) now goes via the bridge; real MetaTrader5 is Windows-only.
import pandas as pd
import numpy as np

from config import SYMBOL_CONFIG


def connect() -> bool:
    """Initialize connection to running MT5 terminal."""
    if not mt5.initialize():
        print(f"MT5 initialize() failed: {mt5.last_error()}")
        return False
    return True


def disconnect():
    mt5.shutdown()


def get_account_info() -> dict:
    info = mt5.account_info()
    if info is None:
        return {}
    return {
        "login":    info.login,
        "broker":   info.company,
        "balance":  info.balance,
        "equity":   info.equity,
        "margin":   info.margin,
        "currency": info.currency,
        "leverage": info.leverage,
        "server":   info.server,
    }


def fetch_ohlcv(symbol: str, timeframe=mt5.TIMEFRAME_M1, bars: int = 10000) -> pd.DataFrame:
    """Fetch OHLCV data from MT5. Splits into 40K-bar chunks if bars > 50K."""
    mt5.symbol_select(symbol, True)
    CHUNK = 40000  # safe single-request limit

    if bars <= CHUNK:
        for attempt in range(3):
            rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, bars)
            if rates is not None and len(rates) > 0:
                break
            time.sleep(2)
        chunks = [rates] if (rates is not None and len(rates) > 0) else []
    else:
        # Fetch in chunks using date-based requests
        from datetime import datetime, timezone
        import math
        n_chunks = math.ceil(bars / CHUNK)
        all_chunks = []
        # Start from the oldest: offset = (n_chunks-1)*CHUNK bars ago
        for chunk_i in range(n_chunks - 1, -1, -1):
            offset = chunk_i * CHUNK
            count  = min(CHUNK, bars - (n_chunks - 1 - chunk_i) * CHUNK)
            for attempt in range(3):
                r = mt5.copy_rates_from_pos(symbol, timeframe, offset, count)
                if r is not None and len(r) > 0:
                    all_chunks.append(r)
                    break
                time.sleep(2)
        import numpy as np
        chunks = all_chunks

    if not chunks:
        print(f"No data returned for {symbol}: {mt5.last_error()}")
        return pd.DataFrame()

    import numpy as np
    rates = np.concatenate(chunks) if len(chunks) > 1 else chunks[0]
    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s")
    df.set_index("time", inplace=True)
    df = df[~df.index.duplicated(keep="last")].sort_index()
    df.rename(columns={
        "open":  "Open",
        "high":  "High",
        "low":   "Low",
        "close": "Close",
        "tick_volume": "Volume",
    }, inplace=True)
    return df[["Open", "High", "Low", "Close", "Volume"]]


def get_pip_size(symbol: str) -> float:
    """Return pip size for symbol (point * 10 for most brokers)."""
    info = mt5.symbol_info(symbol)
    if info is None:
        return 0.0001
    return info.point * 10.0


def check_symbol(symbol: str) -> bool:
    """Verify symbol exists and is available."""
    info = mt5.symbol_info(symbol)
    if info is None:
        print(f"Symbol {symbol} not found in MT5.")
        return False
    if not info.visible:
        mt5.symbol_select(symbol, True)
    return True


def main():
    parser = argparse.ArgumentParser(description="MT5 Bridge — connection test and data fetch")
    parser.add_argument("--symbol", default="EURUSD", help="Symbol to test (default: EURUSD)")
    parser.add_argument("--bars",   type=int, default=1000, help="Number of M1 bars to fetch")
    args = parser.parse_args()

    print("=" * 50)
    print("ScalpMaster HFT — MT5 Bridge")
    print("=" * 50)

    if not connect():
        sys.exit(1)

    # Account info
    acc = get_account_info()
    if acc:
        print(f"\nConnected to MT5")
        print(f"  Broker:   {acc['broker']}")
        print(f"  Login:    {acc['login']}")
        print(f"  Server:   {acc['server']}")
        print(f"  Balance:  ${acc['balance']:.2f} {acc['currency']}")
        print(f"  Equity:   ${acc['equity']:.2f}")
        print(f"  Leverage: 1:{acc['leverage']}")
    else:
        print("Could not retrieve account info.")

    # Symbol test
    symbol = args.symbol.upper()
    print(f"\nFetching {args.bars} M1 bars for {symbol}...")

    if not check_symbol(symbol):
        disconnect()
        sys.exit(1)

    df = fetch_ohlcv(symbol, mt5.TIMEFRAME_M1, args.bars)
    if df.empty:
        print("Failed to fetch data.")
        disconnect()
        sys.exit(1)

    pip = get_pip_size(symbol)
    print(f"\nData info for {symbol}:")
    print(f"  Bars:      {len(df)}")
    print(f"  From:      {df.index[0]}")
    print(f"  To:        {df.index[-1]}")
    print(f"  Pip size:  {pip}")
    print(f"  Price range: {df['Low'].min():.5f} — {df['High'].max():.5f}")
    print(f"  Avg spread (estimate): check in MT5 terminal")

    print(f"\nLast 5 candles:")
    print(df.tail(5).to_string())

    disconnect()
    print("\nMT5 connection closed. Bridge OK.")


if __name__ == "__main__":
    main()
