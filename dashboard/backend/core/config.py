from pathlib import Path

BASE_DIR        = Path(__file__).parents[3]          # "mt5 bot/"
LIVE_STATE_PATH = BASE_DIR / "mt5_bridge" / "_live_state.json"
LIVE_LOG_PATH   = BASE_DIR / "mt5_bridge" / "_live_log.txt"
KNOWLEDGE_BASE  = BASE_DIR / "trading_agents" / "knowledge_base.json"
PERF_LOG        = BASE_DIR / "trading_agents" / "performance_log.json"
SYSTEM_CONFIG   = BASE_DIR / "trading_agents" / "trading_system_config.json"
TRADING_LOG     = BASE_DIR / "trading_system.log"

POLL_INTERVAL   = 5      # seconds between state polls
LOG_TAIL_SEC    = 0.5    # log tailer frequency
MAX_EQUITY_HIST = 1440   # ~24h of per-minute snapshots
LOG_TAIL_LINES  = 500    # in-memory log buffer size
STALE_SECONDS   = 90     # if state file older than this → trader offline
