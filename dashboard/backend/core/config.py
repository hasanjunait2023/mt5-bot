from pathlib import Path

BASE_DIR        = Path(__file__).parents[3]          # "mt5 bot/"
LIVE_STATE_PATH = BASE_DIR / "mt5_bridge" / "_live_state.json"
LIVE_LOG_PATH   = BASE_DIR / "mt5_bridge" / "_live_log.txt"
EA_PERF_PATH    = BASE_DIR / "mt5_bridge" / "_ea_performance.json"
CPP_DAILY_PATH  = BASE_DIR / "mt5_bridge" / "_cpp_daily.json"
CPP_STATE_PATH  = BASE_DIR / "mt5_bridge" / "_cpp_state.json"
ICT_WF_PATH     = BASE_DIR / "backtest_reports" / "ict_wf_results.json"
AGENT_METRICS   = BASE_DIR / "logs" / "agent_metrics.jsonl"
KNOWLEDGE_BASE  = BASE_DIR / "trading_agents" / "knowledge_base.json"
PERF_LOG        = BASE_DIR / "trading_agents" / "performance_log.json"
SYSTEM_CONFIG   = BASE_DIR / "trading_agents" / "trading_system_config.json"
TRADING_LOG     = BASE_DIR / "trading_system.log"

TELEGRAM_HQ_CONFIG = BASE_DIR / "trading_agents" / "telegram_hq_config.json"
TELEGRAM_OUTBOX    = BASE_DIR / "logs" / "telegram" / "outbox.jsonl"

POLL_INTERVAL   = 5      # seconds between state polls
LOG_TAIL_SEC    = 0.5    # log tailer frequency
MAX_EQUITY_HIST = 1440   # ~24h of per-minute snapshots
LOG_TAIL_LINES  = 500    # in-memory log buffer size
STALE_SECONDS   = 90     # if state file older than this → trader offline
