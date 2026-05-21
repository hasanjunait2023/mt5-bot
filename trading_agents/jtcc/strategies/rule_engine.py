"""YAML rule engine — evaluates strategy rules against MarketContext. No Claude API, pure Python."""

from __future__ import annotations

import logging
import re
from typing import Any

log = logging.getLogger("jtcc.rule_engine")

# Supported operators
_OPS = {
    "==": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
    ">=": lambda a, b: a >= b,
    "<=": lambda a, b: a <= b,
    ">": lambda a, b: a > b,
    "<": lambda a, b: a < b,
    "in": lambda a, b: a in b,
    "not in": lambda a, b: a not in b,
    "is true": lambda a, _: a is True or a == True,
    "is false": lambda a, _: a is False or a == False,
}

_OP_PATTERN = re.compile(r"(.+?)\s+(not in|is true|is false|>=|<=|!=|==|>|<|in)\s*(.*)")


def _resolve(path: str, ctx: dict) -> Any:
    """Resolve dotted path like 'market.trend' against context dict."""
    parts = path.strip().split(".")
    val = ctx
    for p in parts:
        if isinstance(val, dict):
            val = val.get(p)
        else:
            return None
    return val


def _coerce(val_str: str, ctx: dict) -> Any:
    """Convert rule value string to Python type."""
    val_str = val_str.strip()
    if val_str.upper() in ("TRUE", "FALSE"):
        return val_str.upper() == "TRUE"
    if val_str.upper() in ("NONE", "NULL"):
        return None
    if val_str.startswith("[") and val_str.endswith("]"):
        items = [v.strip().strip('"').strip("'") for v in val_str[1:-1].split(",") if v.strip()]
        return items
    if val_str.startswith('"') or val_str.startswith("'"):
        return val_str.strip('"').strip("'")
    try:
        return int(val_str)
    except ValueError:
        pass
    try:
        return float(val_str)
    except ValueError:
        pass
    # Try as context path reference (e.g., momentum.atr)
    resolved = _resolve(val_str, ctx)
    if resolved is not None:
        return resolved
    return val_str  # return as-is (string constant like BULLISH)


def _eval_rule(rule: str, ctx: dict) -> bool:
    """Evaluate a single rule string against context."""
    rule = rule.strip()
    m = _OP_PATTERN.match(rule)
    if not m:
        log.debug("Cannot parse rule: %s", rule)
        return False

    lhs_path = m.group(1).strip()
    op_str = m.group(2).strip()
    rhs_str = m.group(3).strip() if m.group(3) else ""

    lhs = _resolve(lhs_path, ctx)
    op_fn = _OPS.get(op_str)
    if op_fn is None:
        return False

    # Unary operators
    if op_str in ("is true", "is false"):
        return op_fn(lhs, None)

    rhs = _coerce(rhs_str, ctx)

    # Type coercion for comparison
    if isinstance(lhs, str) and isinstance(rhs, str):
        return op_fn(lhs.upper(), rhs.upper())
    if isinstance(lhs, (int, float)) and isinstance(rhs, (int, float)):
        return op_fn(float(lhs), float(rhs))

    try:
        return op_fn(lhs, rhs)
    except Exception as e:
        log.debug("Rule eval error '%s': %s", rule, e)
        return False


def _eval_rules_list(rules: list[str], ctx: dict) -> bool:
    """All rules must pass (AND logic)."""
    return all(_eval_rule(r, ctx) for r in rules)


def _calc_sl_tp(direction: str, price: float, exit_rules: dict, ctx: dict) -> tuple[float, float]:
    """Calculate SL and TP from exit rules and market context."""
    atr = ctx.get("momentum", {}).get("atr", price * 0.005)
    sl_method = exit_rules.get("sl_method", "atr")
    tp_method = exit_rules.get("tp_method", "rr")
    sl_buffer = exit_rules.get("sl_buffer_pips", 5)
    min_rr = exit_rules.get("min_rr", 2.0)

    # Calculate SL
    if sl_method == "atr":
        sl_dist = atr * 1.5
    elif sl_method == "sweep_low":
        last_sl = ctx.get("market_structure", {}).get("last_swing_low", price - atr * 2)
        sl_dist = abs(price - (last_sl or price - atr * 2))
    elif sl_method == "swing_low":
        swing_low = ctx.get("market", {}).get("key_levels", [price - atr * 2])
        sl_dist = abs(price - swing_low[0]) if swing_low else atr * 2
    else:
        sl_dist = atr * 2

    # Add buffer in price terms (approximate pips * pip_value)
    pip_val = 0.0001 if price < 100 else 0.01 if price < 1000 else 0.1
    sl_dist += sl_buffer * pip_val

    if direction == "BUY":
        sl = round(price - sl_dist, 5)
        tp = round(price + sl_dist * min_rr, 5)
    else:
        sl = round(price + sl_dist, 5)
        tp = round(price - sl_dist * min_rr, 5)

    return sl, tp


class RuleEngine:
    """Evaluates a strategy YAML definition against a MarketContext dict."""

    def evaluate(self, strategy: dict, ctx: dict) -> dict[str, Any]:
        """
        Returns: {signal: BUY/SELL/NONE, confidence: 0-10, entry, sl, tp, rr_ratio, reason}
        """
        name = strategy.get("name", "unknown")
        symbol = ctx.get("symbol", "")
        symbols = strategy.get("symbols", [])

        if symbols and symbol not in symbols:
            return {"signal": "NONE", "strategy": name, "reason": f"{symbol} not in strategy symbols"}

        entry_rules = strategy.get("entry_rules", {})
        exit_rules = strategy.get("exit_rules", {})
        risk_cfg = strategy.get("risk", {})

        buy_rules = entry_rules.get("buy", [])
        sell_rules = entry_rules.get("sell", [])

        buy_ok = bool(buy_rules) and _eval_rules_list(buy_rules, ctx)
        sell_ok = bool(sell_rules) and _eval_rules_list(sell_rules, ctx)

        if not buy_ok and not sell_ok:
            return {"signal": "NONE", "strategy": name, "confidence": 0,
                    "reason": "No entry conditions met"}

        direction = "BUY" if buy_ok else "SELL"
        price = ctx.get("price", {}).get("mid", ctx.get("price", {}).get("ask", 0))
        if not price:
            return {"signal": "NONE", "strategy": name, "reason": "No price data"}

        sl, tp = _calc_sl_tp(direction, price, exit_rules, ctx)
        rr = round(abs(tp - price) / abs(price - sl), 2) if abs(price - sl) > 0 else 0

        # Confidence: base 5, +1 for each bonus factor
        confidence = 5.0
        if ctx.get("session", {}).get("primary"):
            confidence += 1.0
        if ctx.get("smc", {}).get("sweep_detected"):
            confidence += 1.0
        if ctx.get("smc", {}).get("in_ote"):
            confidence += 1.5
        if ctx.get("market", {}).get("bos"):
            confidence += 0.5
        if ctx.get("momentum", {}).get("adx", 0) > 25:
            confidence += 1.0
        confidence = round(min(10, confidence), 1)

        passed_rules = buy_rules if buy_ok else sell_rules
        return {
            "signal": direction,
            "strategy": name,
            "confidence": confidence,
            "entry": round(price, 5),
            "sl": sl,
            "tp": tp,
            "rr_ratio": rr,
            "rules_passed": len(passed_rules),
            "reason": f"{direction} signal: {len(passed_rules)} rules passed (conf {confidence})",
        }
