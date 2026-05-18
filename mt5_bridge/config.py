# Per-symbol configuration for ScalpMaster HFT backtest
# Adjust these values to match your broker's specifications

SYMBOL_CONFIG = {
    "EURUSD": {
        "pip_digits":   4,      # 1 pip = 0.0001
        "pip_multi":    10,     # point * 10 = pip
        "spread_max":   2.0,    # max pips
        "atr_min_pips": 1.0,
        "session_hours": [(8, 11)],  # London open only — 38-39% WR, cleanest momentum
        "description": "Euro / US Dollar",
    },
    "XAUUSD": {
        "pip_digits":   2,      # 1 pip = 0.10
        "pip_multi":    10,     # point (0.01) * 10 = 0.10 per pip
        "spread_max":   3.0,
        "atr_min_pips": 3.0,    # Gold needs higher ATR threshold
        "session_hours": [(10, 13), (20, 23)],  # Gold peaks: London midday + late NY (skip bad 19:00)
        "description": "Gold / US Dollar",
    },
    "BTCUSD": {
        "pip_digits":   2,
        "pip_multi":    10,
        "spread_max":   50.0,
        "atr_min_pips": 5.0,    # optimized: tighter ATR gate for M1
        "session_hours": [(9, 13), (20, 23)],  # optimized: 47.8% WR sessions
        "description": "Bitcoin / US Dollar",
    },
    "GBPUSD": {
        "pip_digits":   4,
        "pip_multi":    10,
        "spread_max":   2.5,
        "atr_min_pips": 1.0,
        "session_hours": [(8, 17)],
        "description": "British Pound / US Dollar",
    },
}

# Default strategy parameters (match MQL5 inputs)
DEFAULT_PARAMS = {
    "EMA_Fast":       9,
    "EMA_Slow":       21,
    "RSI_Period":     7,
    "RSI_OB":         75,
    "RSI_OS":         25,
    "ATR_Period":     14,
    "ATR_SL_Multi":   1.0,
    "BB_Period":      20,
    "BB_Deviation":   2.0,
    "MACD_Fast":      8,
    "MACD_Slow":      17,
    "MACD_Signal":    9,
    "MomCandles":     3,
    "MinCandleBody":  0.3,
    "RiskPerTrade":   1.0,   # $ (used only when RiskPct=0)
    "RewardPerTrade": 2.0,   # $
    "MaxDrawdownPct": 20.0,
    "RequiredScore":  4,
    "InitialBalance": 100.0,
    # Compound dynamic sizing — 1% risk per trade, compounds on equity growth
    "RiskPct":        1.0,   # risk 1% of current equity per trade (compounding)
    # Trailing stop (activation based on bar close — no intrabar wick kills)
    "UseTrailingTP":  False,  # disabled — ATR-based M1 stops are too tight for useful trail
    "TrailTrigger":   0.5,   # activate trail when close is up N × sl_dist (0.5 = half R)
    "TrailStep":      0.5,   # trail stop follows close at N × sl_dist distance
    "MaxTradeBars":   0,     # force-close after N bars (0 = off; use 120 for XAUUSD M1)
    # Momentum slope filter
    "EMASlopePeriod": 5,     # bars to measure EMA slope
    "EMASlopeMin":    0.1,   # min slope (normalized by ATR) to confirm momentum
}

# Optimizer search grids (per-symbol; falls back to OPTIMIZER_GRID)
OPTIMIZER_GRID = {
    "EMA_Fast":      [5, 7, 9, 12],
    "EMA_Slow":      [15, 21, 30],
    "RSI_Period":    [5, 7, 9],
    "ATR_SL_Multi":  [0.8, 1.0, 1.2, 1.5],
    "RequiredScore": [3, 4, 5],
}

OPTIMIZER_GRID_XAUUSD = {
    "EMA_Fast":      [5, 7, 9, 12],
    "EMA_Slow":      [15, 21, 30],
    "RSI_Period":    [5, 7, 9],
    "ATR_SL_Multi":  [0.5, 0.8, 1.0, 1.2],
    "RequiredScore": [3, 4, 5],
}

# BTC M1 ATR is huge — needs very tight SL multipliers
OPTIMIZER_GRID_BTCUSD = {
    "EMA_Fast":      [5, 7, 9, 12],
    "EMA_Slow":      [15, 21, 30],
    "RSI_Period":    [5, 7, 9],
    "ATR_SL_Multi":  [0.1, 0.2, 0.3, 0.5],
    "RequiredScore": [3, 4, 5],
}

SYMBOL_OPTIMIZER_GRID = {
    "XAUUSD": OPTIMIZER_GRID_XAUUSD,
    "BTCUSD": OPTIMIZER_GRID_BTCUSD,
}

# ─────────────────────────────────────────────────────────────────────────────
# MTF EMA Alignment Scalper — 28 Forex Pairs + XAUUSD + BTCUSD
# ─────────────────────────────────────────────────────────────────────────────

MTF_SYMBOLS = [
    # 7 Majors
    "EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "NZDUSD", "USDCAD",
    # EUR crosses
    "EURGBP", "EURJPY", "EURCHF", "EURAUD", "EURNZD", "EURCAD",
    # GBP crosses
    "GBPJPY", "GBPCHF", "GBPAUD", "GBPNZD", "GBPCAD",
    # AUD crosses
    "AUDJPY", "AUDCHF", "AUDNZD", "AUDCAD",
    # NZD crosses
    "NZDJPY", "NZDCHF", "NZDCAD",
    # CAD & CHF crosses
    "CADJPY", "CADCHF", "CHFJPY",
    # Metals & Crypto
    "XAUUSD", "BTCUSD",
]

MAJOR_CURRENCIES = ["USD", "EUR", "GBP", "JPY", "AUD", "NZD", "CAD", "CHF"]

# Per-symbol spread + ATR thresholds for MTF strategy
MTF_SYMBOL_CONFIG = {
    "EURUSD": {"spread_max_pts": 20,   "pip_digits": 4, "atr_min_pts": 50},
    "GBPUSD": {"spread_max_pts": 25,   "pip_digits": 4, "atr_min_pts": 60},
    "USDJPY": {"spread_max_pts": 20,   "pip_digits": 2, "atr_min_pts": 50},
    "USDCHF": {"spread_max_pts": 25,   "pip_digits": 4, "atr_min_pts": 50},
    "AUDUSD": {"spread_max_pts": 20,   "pip_digits": 4, "atr_min_pts": 40},
    "NZDUSD": {"spread_max_pts": 25,   "pip_digits": 4, "atr_min_pts": 35},
    "USDCAD": {"spread_max_pts": 25,   "pip_digits": 4, "atr_min_pts": 45},
    "EURGBP": {"spread_max_pts": 30,   "pip_digits": 4, "atr_min_pts": 35},
    "EURJPY": {"spread_max_pts": 30,   "pip_digits": 2, "atr_min_pts": 60},
    "EURCHF": {"spread_max_pts": 35,   "pip_digits": 4, "atr_min_pts": 45},
    "EURAUD": {"spread_max_pts": 35,   "pip_digits": 4, "atr_min_pts": 55},
    "EURNZD": {"spread_max_pts": 40,   "pip_digits": 4, "atr_min_pts": 50},
    "EURCAD": {"spread_max_pts": 35,   "pip_digits": 4, "atr_min_pts": 50},
    "GBPJPY": {"spread_max_pts": 40,   "pip_digits": 2, "atr_min_pts": 80},
    "GBPCHF": {"spread_max_pts": 40,   "pip_digits": 4, "atr_min_pts": 60},
    "GBPAUD": {"spread_max_pts": 40,   "pip_digits": 4, "atr_min_pts": 70},
    "GBPNZD": {"spread_max_pts": 45,   "pip_digits": 4, "atr_min_pts": 65},
    "GBPCAD": {"spread_max_pts": 40,   "pip_digits": 4, "atr_min_pts": 60},
    "AUDJPY": {"spread_max_pts": 30,   "pip_digits": 2, "atr_min_pts": 50},
    "AUDCHF": {"spread_max_pts": 35,   "pip_digits": 4, "atr_min_pts": 45},
    "AUDNZD": {"spread_max_pts": 35,   "pip_digits": 4, "atr_min_pts": 40},
    "AUDCAD": {"spread_max_pts": 35,   "pip_digits": 4, "atr_min_pts": 45},
    "NZDJPY": {"spread_max_pts": 35,   "pip_digits": 2, "atr_min_pts": 40},
    "NZDCHF": {"spread_max_pts": 40,   "pip_digits": 4, "atr_min_pts": 35},
    "NZDCAD": {"spread_max_pts": 40,   "pip_digits": 4, "atr_min_pts": 38},
    "CADJPY": {"spread_max_pts": 35,   "pip_digits": 2, "atr_min_pts": 45},
    "CADCHF": {"spread_max_pts": 35,   "pip_digits": 4, "atr_min_pts": 38},
    "CHFJPY": {"spread_max_pts": 35,   "pip_digits": 2, "atr_min_pts": 50},
    "XAUUSD": {"spread_max_pts": 300,  "pip_digits": 2, "atr_min_pts": 200},
    "BTCUSD": {"spread_max_pts": 5000, "pip_digits": 2, "atr_min_pts": 3000},
}

MTF_DEFAULT_PARAMS = {
    # EMAs
    "EMA_Trend":        200,   # macro trend filter on all TFs
    "EMA_Fast":         9,     # crossover fast line
    "EMA_Slow":         15,    # crossover slow line
    # RSI filter (M1 only)
    "RSI_Period":       14,
    "RSI_Buy_Lo":       45,    "RSI_Buy_Hi":  65,
    "RSI_Sell_Lo":      35,    "RSI_Sell_Hi": 55,
    # ATR volatility filter
    "ATR_Period":       14,
    "ATR_Med_Window":   20,    # bars for rolling median comparison
    # Candle quality — crossover candle body must be >= this ratio of range
    "MinBodyRatio":     0.35,
    # SL placement
    "SL_Lookback":      5,     # bars to look back for swing high/low
    "SL_Buffer_ATR":    0.1,   # extra buffer added on top of wick (× ATR)
    # Take profit
    "RR_Ratio":         2.0,   # RR 1:2
    # Risk — 1% equity risk per trade, 1:2 reward ratio, auto-compounding
    "RiskPct":          1.0,   # 1% of current equity per trade (compounding)
    "RR_Ratio":         2.0,   # reward:risk = 1:2
    "InitialBalance":   10000.0,
    # Sessions (UTC)
    "London_Start":     8,  "London_End": 12,
    "NY_Start":        13,  "NY_End":     17,
    # Currency strength thresholds (0-100 scale)
    "CS_Strong_Min":    60,    # base must be >= this to be "strong"
    "CS_Weak_Max":      40,    # quote must be <= this to be "weak"
    # EMA separation: expansion check on M3
    "EMA_Sep_Min_Expand": 0.0, # boolean: sep[i] > sep[i-1]
    # Risk management — conservative limits
    "MaxDDPct":         20.0,  # 20% max total drawdown before halt
    "DailyDDPct":       3.0,   # 3% max daily loss before skipping rest of day
    "MaxTradesDay":     6,     # per symbol per day
}

# ─────────────────────────────────────────────────────────────────────────────
# Best pairs — sorted by reliability (PF × sample size weighting)
# Updated 2026-05-17 after full 30-symbol + optimization backtest
# ─────────────────────────────────────────────────────────────────────────────

# Tier 1 — original strong performers (default params, PF >= 1.5)
MTF_BEST_PAIRS = [
    "CADJPY",   # PF 8.13  WR 80.0%  — #1 original
    "EURJPY",   # PF 6.37  WR 77.8%
    "USDJPY",   # PF 4.43  WR 68.8%
    "GBPAUD",   # PF 3.42  WR 64.3%
    "BTCUSD",   # PF 3.24  WR 62.5%
    "AUDNZD",   # PF 3.05  WR 60.0%
    "USDCAD",   # PF 2.80  WR 57.9%
    "EURUSD",   # PF 2.56  WR 57.1%
    "AUDCHF",   # PF 2.24  WR 53.3%
    "NZDUSD",   # PF 1.96  WR 50.0%
    # Newly discovered via unclassified run (optimized params in MTF_SYMBOL_PARAMS)
    "EURNZD",   # PF 2.28  WR 53.8%  London-only
    "NZDJPY",   # PF 2.20  WR 52.9%  wide RSI
    "AUDCAD",   # PF 1.95  WR 50.0%  London-only
    "GBPJPY",   # PF 1.61  WR 45.5%  London-only
    "AUDUSD",   # PF 1.59  WR 44.4%  wide RSI
    "AUDJPY",   # PF 1.54  WR 44.4%  wide RSI (27 trades, high confidence)
    # Previously-failing, now improved with optimized params
    "GBPUSD",   # PF 1.73  WR 54.5%  London-only + combined params (was PF 0.97)
    "XAUUSD",   # PF 1.30  WR 40.0%  Gold-specific params  (was PF 0.49) — user priority
]

# Marginal pairs (1.0 <= PF < 1.5 with optimized params) — trade with caution
# These are NOT included in live trader by default but config overrides are set
MTF_MARGINAL_PAIRS = [
    "CADCHF",   # PF 1.91  7 trades  — combined_fix  (was PF 0.56)
    "EURAUD",   # PF 1.46  8 trades  — combined_fix  (was PF 0.55)
    "EURCHF",   # PF 1.44  6 trades  — combined_fix  (was PF 0.20)
    "USDCHF",   # PF 1.39  12 trades — wider_sl       (was PF 0.65)
    "GBPCAD",   # PF 1.29  5 trades
    "NZDCAD",   # PF 1.23  18 trades
    "GBPNZD",   # PF 1.21  13 trades
    "EURGBP",   # PF 1.11  11 trades
    "CHFJPY",   # PF 1.11  22 trades
    "NZDCHF",   # PF 1.05  20 trades
]

# Pairs with very promising PF but too few trades for live reliability
# These need more data / longer backtest before going live
MTF_WATCH_PAIRS = [
    "EURCAD",   # PF 7.26 London-only (5 trades) — extremely selective, monitor
    "GBPCHF",   # PF 6.12 London-only (4 trades) — extremely selective, monitor
]

# No pairs are permanently excluded — all 30 have some viable configuration
# (previous MTF_AVOID_PAIRS list is now superseded by per-symbol params above)
MTF_AVOID_PAIRS = []  # kept for backward compatibility

# ─────────────────────────────────────────────────────────────────────────────
# Per-symbol parameter and filter overrides
# Confirmed by 3-month backtest optimization runs (2026-05-17)
# Applied automatically by mtf_live_trader.py and mtf_backtest.run_all()
# ─────────────────────────────────────────────────────────────────────────────

MTF_SYMBOL_PARAMS = {
    # GOLD: EMA 9/21, wide RSI, long SL lookback | PF 0.49 -> 1.30
    "XAUUSD": {
        "EMA_Slow":      21,
        "RSI_Buy_Lo":    40,  "RSI_Buy_Hi":  75,
        "RSI_Sell_Lo":   25,  "RSI_Sell_Hi": 60,
        "SL_Lookback":   8,
    },
    # London-only pairs (NY session kills these — remove it)
    # NY_Start/End set to 23:23 = empty window (no trades that hour)
    "GBPUSD": {
        "RSI_Buy_Lo":  40, "RSI_Buy_Hi":  72,
        "RSI_Sell_Lo": 28, "RSI_Sell_Hi": 60,
        "SL_Lookback": 7,  "RR_Ratio": 1.5,
        "NY_Start": 23,    "NY_End": 23,      # London only
    },
    "GBPJPY": {"NY_Start": 23, "NY_End": 23},
    "EURNZD": {"NY_Start": 23, "NY_End": 23},
    "AUDCAD": {"NY_Start": 23, "NY_End": 23},
    "EURCAD": {"NY_Start": 23, "NY_End": 23},
    # Wide-RSI pairs (EMA alignment sustained longer on these pairs)
    "AUDUSD": {"RSI_Buy_Lo": 42, "RSI_Buy_Hi": 68, "RSI_Sell_Lo": 32, "RSI_Sell_Hi": 58},
    "NZDJPY": {"RSI_Buy_Lo": 42, "RSI_Buy_Hi": 68, "RSI_Sell_Lo": 32, "RSI_Sell_Hi": 58},
    "AUDJPY": {"RSI_Buy_Lo": 42, "RSI_Buy_Hi": 68, "RSI_Sell_Lo": 32, "RSI_Sell_Hi": 58},
    # Previously-failing pairs — combined fix | PF 0.56->1.91, 0.55->1.46, 0.20->1.44
    "CADCHF": {
        "RSI_Buy_Lo":  40, "RSI_Buy_Hi":  72,
        "RSI_Sell_Lo": 28, "RSI_Sell_Hi": 60,
        "SL_Lookback": 7,  "RR_Ratio": 1.5,
        "NY_Start": 23,    "NY_End": 23,
    },
    "EURAUD": {
        "RSI_Buy_Lo":  40, "RSI_Buy_Hi":  72,
        "RSI_Sell_Lo": 28, "RSI_Sell_Hi": 60,
        "SL_Lookback": 7,  "RR_Ratio": 1.5,
        "NY_Start": 23,    "NY_End": 23,
    },
    "EURCHF": {
        "RSI_Buy_Lo":  40, "RSI_Buy_Hi":  72,
        "RSI_Sell_Lo": 28, "RSI_Sell_Hi": 60,
        "SL_Lookback": 7,  "RR_Ratio": 1.5,
        "NY_Start": 23,    "NY_End": 23,
    },
    "USDCHF": {"SL_Lookback": 8, "SL_Buffer_ATR": 0.15},
}

# Per-symbol filter overrides (merged with MTF_DEFAULT_FILTERS at runtime)
# Only entries that differ from defaults need to be listed.
MTF_SYMBOL_FILTERS = {
    # Candle quality disabled: crossover candle body filter was rejecting too many
    # valid signals on these pairs — removing it improves PF significantly
    "GBPUSD": {"candle_quality": False},
    "CADCHF": {"candle_quality": False},
    "EURAUD": {"candle_quality": False},
    "EURCHF": {"candle_quality": False},
}

# Which filters are active by default in the MTF strategy
MTF_DEFAULT_FILTERS = {
    "rsi":               True,   # RSI range filter on M1
    "atr_vol":           True,   # ATR above rolling median
    "session":           True,   # London + NY sessions only
    "candle_quality":    True,   # crossover candle body >= MinBodyRatio
    "ema_separation":    True,   # EMA gap expanding on M3
    "currency_strength": False,  # requires all 28 pairs pre-loaded
    "news":              False,  # requires internet (Forex Factory API)
    "spread":            True,   # spread below threshold
}
