from fastapi import APIRouter
from core.state_manager import poller

router = APIRouter()


@router.get("/agents")
def get_agents():
    state = poller.get_snapshot()
    kb    = poller.get_knowledge_base()
    pl    = poller.get_perf_log()

    symbol_stats = {}
    for sym, data in kb.get("symbols", {}).items():
        symbol_stats[sym] = {
            "successful_patterns": len(data.get("successful_patterns", [])),
            "failed_patterns":     len(data.get("failed_patterns", [])),
            "regime_performance":  data.get("regime_performance", {}),
        }

    return {
        "live_trader": {
            "running":        state.get("trader_running", False),
            "mt5_connected":  state.get("mt5_connected", False),
            "symbols":        state.get("symbols", []),
            "last_signals":   state.get("last_signals", {}),
            "daily_trades":   state.get("daily_trades", {}),
            "timestamp":      state.get("timestamp"),
        },
        "strategy_researcher": {
            **state.get("agents", {}).get("strategy_researcher", {}),
            "symbol_stats": symbol_stats,
        },
        "performance_optimizer": state.get("agents", {}).get("performance_optimizer", {}),
        "execution_manager":    state.get("agents", {}).get("execution_manager", {}),
    }
