"""
Execution & Risk Agent - Manages live trading, risk controls, and position sizing.
Handles trade execution, risk management, and portfolio controls.
"""

import json
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional, Any
import threading
import time
import queue
import logging

from mt5_bridge import connect, disconnect, fetch_ohlcv, get_pip_size, check_symbol, place_order, modify_order, close_order
from config import SYMBOL_CONFIG, DEFAULT_PARAMS
from mt5_bridge.enhanced_backtest import WalkForwardAnalyzer
from mt5_bridge.ml_enhanced_signals import MLCSignalFilter
from backtest import (
    add_indicators, compute_signals, simulate_trades, compute_metrics
)


class ExecutionManager:
    """Manages live trade execution, risk controls, and position sizing."""

    def __init__(self, account_balance: float = 10000.0, max_risk_per_trade: float = 0.01):
        self.account_balance = account_balance
        self.initial_balance = account_balance   # tracks starting equity for drawdown
        self.max_risk_per_trade = max_risk_per_trade  # 1% risk per trade (compounding)
        self.rr_ratio = 2.0                      # 1:2 reward-to-risk ratio
        self.current_positions = {}  # symbol -> position info
        self.daily_pnl = 0.0
        self.max_daily_loss = 0.03  # 3% max daily loss
        self.daily_trade_count = 0
        self.max_daily_trades = 6
        self.is_trading_enabled = True
        self.emergency_stop = False

        # Risk management parameters
        self.max_portfolio_risk = 0.06   # 6% max total open risk (6 trades × 1%)
        self.max_correlation_exposure = 0.30  # 30% max in correlated pairs
        self.max_drawdown_limit = 0.15   # 15% max drawdown before halving risk

        # Performance tracking
        self.trade_history = []
        self.performance_metrics = {
            "total_trades": 0,
            "winning_trades": 0,
            "losing_trades": 0,
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "sharpe_ratio": 0.0,
            "max_drawdown": 0.0,
            "current_drawdown": 0.0
        }

        # Threading for real-time operations
        self.signal_queue = queue.Queue()
        self.execution_thread = None
        self.is_running = False

        # Setup logging
        logging.basicConfig(level=logging.INFO)
        self.logger = logging.getLogger(__name__)

    def sync_equity(self, live_equity: float):
        """Update account_balance to live equity for compounding. Call after each trade close."""
        if live_equity > 0:
            self.account_balance = live_equity

    def calculate_position_size(self, symbol: str, signal_confidence: float,
                              stop_loss_pips: float, strategy_performance: Dict = None) -> float:
        """
        Calculate position size: 1% equity risk per trade, compounds automatically.
        Lot = (Equity × RiskPct) / (SL_pips × pip_value_per_lot)
        """
        try:
            pip_size = get_pip_size(symbol)

            # Always risk exactly 1% of current equity (compounding effect)
            base_risk = self.account_balance * self.max_risk_per_trade  # 1% of equity

            # Scale confidence slightly (0.8–1.0 range, never go below 80% of base risk)
            confidence_multiplier = max(0.8, min(1.0, signal_confidence))

            # Drawdown protection: halve position size if drawdown > 10%
            drawdown_multiplier = 1.0
            current_dd = self.performance_metrics.get("current_drawdown", 0.0)
            if current_dd > 15.0:   # above 15% DD → half size
                drawdown_multiplier = 0.5
            elif current_dd > 10.0: # above 10% DD → 75% size
                drawdown_multiplier = 0.75

            # Daily loss protection: half size once 50% of daily limit hit
            daily_multiplier = 1.0
            if self.daily_pnl < -self.account_balance * self.max_daily_loss * 0.5:
                daily_multiplier = 0.5

            adjusted_risk = base_risk * confidence_multiplier * drawdown_multiplier * daily_multiplier

            # Pip value per standard lot (1 lot = 100,000 units)
            pip_value = 10.0  # EURUSD, GBPUSD, most majors
            if "JPY" in symbol:
                pip_value = 1000.0 / 100.0  # ~$6.80 per pip, approximate as 10 for safety
            elif "XAU" in symbol or "GOLD" in symbol:
                pip_value = 10.0  # $10 per pip (1 pip = $0.10 × 100 lot units)
            elif "BTC" in symbol:
                pip_value = 1.0   # varies; conservative fallback

            stop_loss_value = stop_loss_pips * pip_value
            if stop_loss_value > 0:
                lots = adjusted_risk / stop_loss_value
            else:
                lots = 0.01

            # Lot constraints: min 0.01, max 2% of equity / 1000 (safety cap)
            min_lot = 0.01
            max_lot = min(5.0, self.account_balance / 2000)
            lots = max(min_lot, min(max_lot, lots))

            return round(lots, 2)

        except Exception as e:
            self.logger.error(f"Error calculating position size: {e}")
            return 0.01

    def assess_trade_risk(self, symbol: str, direction: int, entry_price: float,
                         stop_loss: float, take_profit: float, lot_size: float) -> Dict:
        """Assess risk of a potential trade."""
        try:
            risk_assessment = {
                "approved": True,
                "warnings": [],
                "rejections": [],
                "adjusted_lot_size": lot_size,
                "risk_reward_ratio": 0.0,
                "max_loss": 0.0,
                "max_profit": 0.0
            }

            # Calculate pip sizes and values
            pip_size = get_pip_size(symbol)
            sym_cfg = SYMBOL_CONFIG.get(symbol, SYMBOL_CONFIG["EURUSD"])

            # Risk per pip calculation
            if direction == 1:  # BUY
                sl_pips = abs(entry_price - stop_loss) / pip_size
                tp_pips = abs(take_profit - entry_price) / pip_size
            else:  # SELL
                sl_pips = abs(stop_loss - entry_price) / pip_size
                tp_pips = abs(entry_price - take_profit) / pip_size

            # Get pip value (simplified)
            pip_value = 10.0  # Base value
            if "JPY" in symbol:
                pip_value = 100.0 / pip_size if pip_size > 0 else 10.0
            elif "XAU" in symbol or "GOLD" in symbol:
                pip_value = 1.0

            # Calculate monetary risk/reward
            risk_per_pip = lot_size * pip_value
            reward_per_pip = lot_size * pip_value

            max_loss = sl_pips * risk_per_pip
            max_profit = tp_pips * reward_per_pip

            risk_assessment["max_loss"] = max_loss
            risk_assessment["max_profit"] = max_profit

            if max_loss > 0:
                risk_assessment["risk_reward_ratio"] = max_profit / max_loss

            # Risk checks
            # 0. Minimum RR ratio check (must be at least 1:2)
            if max_loss > 0 and risk_assessment["risk_reward_ratio"] < self.rr_ratio:
                risk_assessment["rejections"].append(
                    f"RR {risk_assessment['risk_reward_ratio']:.2f} below minimum 1:{self.rr_ratio}"
                )

            # 1. Individual trade risk limit (max 1% per trade)
            trade_risk_pct = max_loss / self.account_balance
            if trade_risk_pct > self.max_risk_per_trade:
                risk_assessment["rejections"].append(
                    f"Trade risk {trade_risk_pct:.1%} exceeds limit {self.max_risk_per_trade:.1%}"
                )
                # Adjust lot size to meet risk limit
                max_allowed_loss = self.account_balance * self.max_risk_per_trade
                if max_loss > 0:
                    adjusted_lot_size = lot_size * (max_allowed_loss / max_loss)
                    risk_assessment["adjusted_lot_size"] = max(0.01, round(adjusted_lot_size, 2))

            # 2. Daily loss limit
            potential_daily_loss = self.daily_pnl - max_loss
            if potential_daily_loss < -self.account_balance * self.max_daily_loss:
                risk_assessment["rejections"].append(
                    f"Trade would exceed daily loss limit"
                )

            # 3. Daily trade count limit
            if self.daily_trade_count >= self.max_daily_trades:
                risk_assessment["rejections"].append(
                    f"Daily trade limit ({self.max_daily_trades}) reached"
                )

            # 4. Portfolio risk check (simplified)
            current_exposure = sum(pos.get("market_value", 0) for pos in self.current_positions.values())
            new_exposure = abs(entry_price * lot_size * 100)  # Approximate
            total_exposure = current_exposure + new_exposure

            if total_exposure > self.account_balance * 5:  # 5x leverage limit
                risk_assessment["warnings"].append("High leverage usage detected")

            # 5. Correlation risk (simplified - would be more complex in practice)
            # For now, just check if we already have a position in this symbol
            if symbol in self.current_positions:
                existing_pos = self.current_positions[symbol]
                if existing_pos.get("direction") == direction:
                    risk_assessment["warnings"].append(
                        f"Already have {direction} position in {symbol}"
                    )

            # Final approval decision
            risk_assessment["approved"] = len(risk_assessment["rejections"]) == 0

            if risk_assessment["warnings"]:
                self.logger.warning(f"Risk warnings for {symbol}: {risk_assessment['warnings']}")

            if not risk_assessment["approved"]:
                self.logger.info(f"Trade rejected for {symbol}: {risk_assessment['rejections']}")

            return risk_assessment

        except Exception as e:
            self.logger.error(f"Error assessing trade risk: {e}")
            return {
                "approved": False,
                "warnings": [],
                "rejections": [f"Risk assessment error: {e}"],
                "adjusted_lot_size": lot_size
            }

    def execute_trade(self, symbol: str, direction: int, entry_price: float,
                     stop_loss: float, take_profit: float, lot_size: float,
                     signal_confidence: float = 0.5, strategy_id: str = None) -> Dict:
        """Execute a trade with risk management."""
        try:
            # Assess risk first
            risk_assessment = self.assess_trade_risk(
                symbol, direction, entry_price, stop_loss, take_profit, lot_size
            )

            if not risk_assessment["approved"]:
                return {
                    "success": False,
                    "reason": "Risk assessment failed",
                    "details": risk_assessment
                }

            # Use adjusted lot size if risk assessment modified it
            final_lot_size = risk_assessment["adjusted_lot_size"]

            # Place the order via MT5
            # This is a simplified version - in practice would use proper MT5 API calls
            trade_id = f"{symbol}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"

            # Prepare trade record
            trade_record = {
                "trade_id": trade_id,
                "symbol": symbol,
                "direction": direction,  # 1 for BUY, -1 for SELL
                "entry_price": entry_price,
                "stop_loss": stop_loss,
                "take_profit": take_profit,
                "lot_size": final_lot_size,
                "signal_confidence": signal_confidence,
                "strategy_id": strategy_id,
                "entry_time": datetime.now(),
                "status": "open",
                "risk_assessment": risk_assessment
            }

            # In a real implementation, this would call the MT5 API:
            # order_result = place_order(
            #     symbol=symbol,
            #     order_type=mt5.ORDER_TYPE_BUY if direction == 1 else mt5.ORDER_TYPE_SELL,
            #     volume=final_lot_size,
            #     price=entry_price,
            #     sl=stop_loss,
            #     tp=take_profit,
            #     comment=f"AI_Strategy_{strategy_id or 'unknown'}"
            # )

            # For now, simulate successful execution
            self.logger.info(f"Executing {direction} trade: {symbol} {final_lot_size} lots @ {entry_price}")
            self.logger.info(f"SL: {stop_loss}, TP: {take_profit}")

            # Add to current positions
            self.current_positions[symbol] = {
                "trade_id": trade_id,
                "direction": direction,
                "entry_price": entry_price,
                "stop_loss": stop_loss,
                "take_profit": take_profit,
                "lot_size": final_lot_size,
                "entry_time": datetime.now(),
                "signal_confidence": signal_confidence,
                "strategy_id": strategy_id
            }

            # Update counters
            self.daily_trade_count += 1

            return {
                "success": True,
                "trade_id": trade_id,
                "trade_record": trade_record,
                "lot_size_used": final_lot_size,
                "risk_assessment": risk_assessment
            }

        except Exception as e:
            self.logger.error(f"Error executing trade: {e}")
            return {
                "success": False,
                "reason": f"Execution error: {e}"
            }

    def manage_open_positions(self, current_prices: Dict[str, float]) -> List[Dict]:
        """Manage open positions - check for SL/TP hits, trailing stops, etc."""
        closed_positions = []

        for symbol, position in list(self.current_positions.items()):
            if symbol not in current_prices:
                continue

            current_price = current_prices[symbol]
            direction = position["direction"]
            entry_price = position["entry_price"]
            stop_loss = position["stop_loss"]
            take_profit = position["take_profit"]

            # Check for stop loss hit
            sl_hit = False
            tp_hit = False

            if direction == 1:  # BUY
                if current_price <= stop_loss:
                    sl_hit = True
                elif current_price >= take_profit:
                    tp_hit = True
            else:  # SELL
                if current_price >= stop_loss:
                    sl_hit = True
                elif current_price <= take_profit:
                    tp_hit = True

            if sl_hit or tp_hit:
                # Close the position
                pips_moved = abs(current_price - entry_price) / get_pip_size(symbol)
                if direction == 1:
                    pnl_pips = pips_moved
                else:
                    pnl_pips = -pips_moved

                # Simplified P&L calculation
                pip_value = 10.0  # Base pip value
                if "JPY" in symbol:
                    pip_value = 100.0 / get_pip_size(symbol) if get_pip_size(symbol) > 0 else 10.0
                elif "XAU" in symbol or "GOLD" in symbol:
                    pip_value = 1.0

                pnl = pnl_pips * position["lot_size"] * pip_value

                # Update daily P&L
                self.daily_pnl += pnl

                # Create closed position record
                closed_position = {
                    **position,
                    "exit_price": current_price,
                    "exit_time": datetime.now(),
                    "pnl": pnl,
                    "exit_reason": "TP" if tp_hit else "SL",
                    "pips_moved": pips_moved
                }

                closed_positions.append(closed_position)

                # Remove from current positions
                del self.current_positions[symbol]

                self.logger.info(f"Closed {symbol} position: {closed_position['exit_reason']} "
                               f"P&L: ${pnl:.2f}")

        return closed_positions

    def update_performance_metrics(self):
        """Update performance metrics based on trade history."""
        # This would typically be called periodically or after trades close
        # For now, simplified version

        # Calculate win rate, profit factor, etc. from trade_history
        if not self.trade_history:
            return

        winning_trades = [t for t in self.trade_history if t.get("pnl", 0) > 0]
        losing_trades = [t for t in self.trade_history if t.get("pnl", 0) <= 0]

        self.performance_metrics["total_trades"] = len(self.trade_history)
        self.performance_metrics["winning_trades"] = len(winning_trades)
        self.performance_metrics["losing_trades"] = len(losing_trades)

        if self.performance_metrics["total_trades"] > 0:
            self.performance_metrics["win_rate"] = (
                self.performance_metrics["winning_trades"] / self.performance_metrics["total_trades"]
            ) * 100

        if winning_trades and losing_trades:
            total_profit = sum(t.get("pnl", 0) for t in winning_trades if t.get("pnl", 0) > 0)
            total_loss = abs(sum(t.get("pnl", 0) for t in losing_trades if t.get("pnl", 0) < 0))
            if total_loss > 0:
                self.performance_metrics["profit_factor"] = total_profit / total_loss
            else:
                self.performance_metrics["profit_factor"] = float('inf') if total_profit > 0 else 0.0

        # Calculate drawdown
        if len(self.trade_history) >= 2:
            cumulative_pnl = np.cumsum([t.get("pnl", 0) for t in self.trade_history])
            running_max = np.maximum.accumulate(cumulative_pnl)
            drawdown = (running_max - cumulative_pnl) / np.maximum(running_max, 1) * 100
            self.performance_metrics["current_drawdown"] = drawdown[-1] if len(drawdown) > 0 else 0.0
            self.performance_metrics["max_drawdown"] = max(
                self.performance_metrics.get("max_drawdown", 0.0),
                self.performance_metrics["current_drawdown"]
            )

    def emergency_stop_all(self):
        """Emergency stop - close all positions and disable trading."""
        self.logger.warning("EMERGENCY STOP TRIGGERED")
        self.emergency_stop = True
        self.is_trading_enabled = False
        # In practice, would send close orders for all positions
        self.logger.info("All new trading disabled. Manual position closure recommended.")

    def reset_daily_metrics(self):
        """Reset daily metrics - should be called at start of each trading day."""
        self.daily_pnl = 0.0
        self.daily_trade_count = 0
        self.logger.info("Daily metrics reset")

    def get_status(self) -> Dict:
        """Get current status of the execution manager."""
        return {
            "account_balance": self.account_balance,
            "current_positions": len(self.current_positions),
            "daily_pnl": self.daily_pnl,
            "daily_trades": self.daily_trade_count,
            "is_trading_enabled": self.is_trading_enabled,
            "emergency_stop": self.emergency_stop,
            "performance_metrics": self.performance_metrics.copy(),
            "positions": {sym: {k: v for k, v in pos.items() if k not in ['entry_time', 'exit_time']}
                         for sym, pos in self.current_positions.items()}
        }


def main():
    """Main function for testing the execution manager."""
    import argparse
    parser = argparse.ArgumentParser(description="Execution & Risk Agent")
    parser.add_argument("--balance", type=float, default=10000.0, help="Starting account balance")
    parser.add_argument("--risk", type=float, default=0.02, help="Max risk per trade (as decimal)")

    args = parser.parse_args()

    executor = ExecutionManager(account_balance=args.balance, max_risk_per_trade=args.risk)

    # Example usage
    print("Execution Manager initialized")
    print(f"Account Balance: ${executor.account_balance}")
    print(f"Max Risk per Trade: {executor.max_risk_per_trade*100}%")

    # Test position sizing
    lot_size = executor.calculate_position_size("EURUSD", 0.8, 10.0)
    print(f"Example position size for EURUSD: {lot_size} lots")

    # Show status
    status = executor.get_status()
    print("\nCurrent Status:")
    print(json.dumps(status, indent=2, default=str))


if __name__ == "__main__":
    main()