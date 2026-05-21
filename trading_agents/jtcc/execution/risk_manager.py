"""Hard risk rules enforcement — 1% equity per trade, 6% daily DD shutdown."""

from __future__ import annotations

import json
import logging
from pathlib import Path

log = logging.getLogger("jtcc.risk")

BASE_DIR = Path(__file__).parent.parent.parent.parent
LIVE_STATE = BASE_DIR / "mt5_bridge" / "_live_state.json"
KILL_SWITCH = BASE_DIR / "mt5_bridge" / "_kill_switch.json"

# Min SL distance in price terms (not pips) per symbol
MIN_SL_DIST = {
    "XAUUSD": 0.50,    # 50 cents
    "XAGUSD": 0.05,
    "BTCUSD": 100.0,
    "EURUSD": 0.0008,  # 8 pips
    "GBPUSD": 0.0010,  # 10 pips
    "USDJPY": 0.08,    # 8 pips
}


def _read_state() -> dict:
    try:
        return json.loads(LIVE_STATE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def get_account() -> dict:
    state = _read_state()
    acc = state.get("account", {})
    equity = acc.get("equity", acc.get("balance", 0))
    balance = acc.get("balance", equity)
    return {"equity": equity, "balance": balance}


def check_daily_dd() -> tuple[bool, float]:
    """Returns (shutdown, current_dd_pct)."""
    state = _read_state()
    acc = state.get("account", {})
    balance = acc.get("balance", acc.get("equity", 0))
    if balance <= 0:
        return False, 0.0
    daily_pnl = state.get("daily_pnl", 0.0)
    dd_pct = abs(daily_pnl / balance * 100) if daily_pnl < 0 else 0.0
    return dd_pct >= 6.0, round(dd_pct, 2)


def can_trade(symbol: str, max_per_symbol: int = 2, max_total: int = 3) -> tuple[bool, str]:
    """Returns (allowed, reason)."""
    shutdown, dd_pct = check_daily_dd()
    if shutdown:
        return False, f"Daily DD {dd_pct:.1f}% >= 6% — SHUTDOWN"

    if KILL_SWITCH.exists():
        try:
            ks = json.loads(KILL_SWITCH.read_text())
            if ks.get("active"):
                return False, "Kill-switch active — manual reset required"
        except Exception:
            pass

    state = _read_state()
    positions = state.get("positions", [])
    if len(positions) >= max_total:
        return False, f"Max {max_total} concurrent trades reached"

    symbol_positions = [p for p in positions if p.get("symbol") == symbol]
    if len(symbol_positions) >= max_per_symbol:
        return False, f"Max {max_per_symbol} trades/day for {symbol}"

    return True, "OK"


def calculate_lot(symbol: str, entry: float, sl: float,
                  risk_pct: float = 1.0,
                  vol_scalar: float = 1.0) -> tuple[float, str]:
    """Returns (lot_size, info_string). Returns 0.0 if invalid.

    Args:
        vol_scalar: Volatility-targeting multiplier (e.g., from TSMOM analytics).
                    Paper: position_size = (40% / σ_annualized) per Moskowitz 2012.
                    Default 1.0 = base sizing. Range clamped [0.1, 5.0].
    """
    acc = get_account()
    equity = acc.get("equity", 0)
    if equity <= 0:
        return 0.0, "No account data"

    sl_dist = abs(entry - sl)
    min_sl = MIN_SL_DIST.get(symbol, 0.0001)
    if sl_dist < min_sl:
        return 0.0, f"SL too close ({sl_dist:.5f} < min {min_sl})"

    # 1% equity risk
    risk_amount = equity * (risk_pct / 100)

    # Approximate pip value (simplified — full version needs MT5 contract specs)
    # For forex: 1 lot = 100,000 units; for gold: 1 lot = 100oz
    if "XAU" in symbol:
        contract_size = 100   # 100 oz per lot
        pip_value_per_lot = sl_dist * contract_size  # P&L per lot for this SL
    elif "XAG" in symbol:
        contract_size = 5000
        pip_value_per_lot = sl_dist * contract_size
    elif "BTC" in symbol:
        contract_size = 1
        pip_value_per_lot = sl_dist * contract_size
    else:
        # Forex: SL in price terms × 100,000 (standard lot) × approximate USD value
        contract_size = 100000
        # For USD pairs, 1 pip ≈ $10/lot; use direct P&L calculation
        if symbol.endswith("USD"):
            pip_value_per_lot = sl_dist * contract_size
        else:
            # Approximate for non-USD quote
            pip_value_per_lot = sl_dist * contract_size * entry

    if pip_value_per_lot <= 0:
        return 0.0, "Zero P&L per lot"

    lot = risk_amount / pip_value_per_lot
    # Apply vol-targeting scalar (TSMOM Moskowitz 2012)
    scalar = max(0.1, min(5.0, vol_scalar))
    lot = lot * scalar
    lot = round(max(0.01, min(lot, 10.0)), 2)  # clamp: 0.01 to 10 lots

    scalar_note = f" × vol_scalar({scalar:.2f})" if scalar != 1.0 else ""
    return lot, f"1% equity ({risk_amount:.2f}) / {pip_value_per_lot:.2f}{scalar_note} = {lot} lots"


def check_spread(symbol: str, entry: float, sl: float, spread: float,
                 max_pct: float = 20.0) -> tuple[bool, str]:
    """Returns (ok, reason). Spread > 20% of SL distance = skip."""
    sl_dist = abs(entry - sl)
    if sl_dist <= 0:
        return False, "Invalid SL distance"
    spread_pct = (spread / sl_dist) * 100
    if spread_pct > max_pct:
        return False, f"Spread {spread_pct:.1f}% > {max_pct}% of SL — skip"
    return True, f"Spread OK ({spread_pct:.1f}% of SL)"


def emergency_close_all(reason: str = "JTCC emergency") -> None:
    """Write kill-switch and notify. Actual close via mt5_client in main loop."""
    log.critical("EMERGENCY CLOSE: %s", reason)
    try:
        KILL_SWITCH.write_text(
            json.dumps({"active": True, "reason": reason, "source": "jtcc_risk_manager"}),
            encoding="utf-8",
        )
    except Exception as e:
        log.error("Kill-switch write failed: %s", e)
    try:
        from trading_agents.telegram_hq import send as tg_send
        tg_send("critical", f"JTCC EMERGENCY: {reason}\nKill-switch activated.", level="CRITICAL",
                title="JTCC DD SHUTDOWN")
    except Exception as e:
        log.error("Emergency notify failed: %s", e)
