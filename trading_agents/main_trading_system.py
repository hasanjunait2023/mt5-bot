"""
Main Trading System - Orchestrates the self-improving trading team.
Brings together Strategy Researcher, Execution Manager, and Performance Optimizer
to create a complete autonomous trading system.
"""

import json
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
import time
import threading
import schedule
import logging
import os
import signal
import sys
from typing import Dict, List, Tuple, Optional, Any

# Import our custom components
from mt5_bridge import connect, disconnect, fetch_ohlcv, get_pip_size, check_symbol
from mt5_bridge.enhanced_backtest import WalkForwardAnalyzer
from mt5_bridge.parameter_optimizer import ParameterOptimizer
from mt5_bridge.ml_enhanced_signals import MLCSignalFilter, ml_enhanced_compute_signals
from mt5_bridge.session_analyzer import SessionAnalyzer
from backtest import (
    add_indicators, compute_signals, simulate_trades, compute_metrics
)
from trading_agents.strategy_researcher import StrategyResearcher
from trading_agents.execution_manager import ExecutionManager
from trading_agents.performance_optimizer import PerformanceOptimizer
from config import SYMBOL_CONFIG, DEFAULT_PARAMS


class MainTradingSystem:
    """Main orchestrator for the self-improving trading system."""

    def __init__(self, config_file: str = "trading_system_config.json"):
        self.config_file = config_file
        self.config = self._load_config()

        # Initialize system components
        self.strategy_researcher = StrategyResearcher()
        self.execution_manager = ExecutionManager(
            account_balance=self.config.get("account_balance", 10000.0),
            max_risk_per_trade=self.config.get("max_risk_per_trade", 0.01)
        )
        self.execution_manager.rr_ratio = self.config.get("rr_ratio", 2.0)
        self.execution_manager.max_daily_loss = self.config.get("max_daily_loss_pct", 0.03)
        self.execution_manager.max_daily_trades = self.config.get("max_daily_trades", 6)
        self.execution_manager.max_drawdown_limit = self.config.get("max_drawdown_pct", 0.20)
        self.performance_optimizer = PerformanceOptimizer()
        self.session_analyzer = SessionAnalyzer()

        # System state
        self.is_running = False
        self.last_research_time = None
        self.last_optimization_time = None
        self.system_thread = None

        # Trading symbols
        self.symbols = self.config.get("symbols", ["EURUSD", "XAUUSD", "GBPUSD"])

        # Performance tracking
        self.system_metrics = {
            "start_time": None,
            "total_cycles": 0,
            "successful_optimizations": 0,
            "total_research_cycles": 0,
            "last_health_check": None
        }

        # Setup logging
        self._setup_logging()

        # Setup signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def _setup_logging(self):
        """Setup logging configuration."""
        log_level = getattr(logging, self.config.get("log_level", "INFO").upper())
        logging.basicConfig(
            level=log_level,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler("trading_system.log"),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger(__name__)
        self.logger.info("Logging initialized")

    def _load_config(self) -> Dict:
        """Load system configuration."""
        default_config = {
            "account_balance": 10000.0,
            "max_risk_per_trade": 0.01,   # 1% equity risk per trade
            "rr_ratio": 2.0,              # 1:2 reward-to-risk
            "compound_on_equity": True,
            "symbols": ["CADJPY", "EURJPY", "USDJPY", "EURUSD", "XAUUSD", "GBPUSD"],
            "research_interval_hours": 6,
            "optimization_interval_hours": 12,
            "health_check_interval_minutes": 30,
            "log_level": "INFO",
            "enable_live_trading": True,
            "demo_account": True,
            "max_daily_trades": 6,
            "max_daily_loss_pct": 0.03,   # 3% daily loss limit
            "max_drawdown_pct": 0.20      # 20% total drawdown halt
        }

        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r') as f:
                    user_config = json.load(f)
                    default_config.update(user_config)
            except Exception as e:
                print(f"Error loading config: {e}. Using default configuration.")
        else:
            # Create default config file
            with open(self.config_file, 'w') as f:
                json.dump(default_config, f, indent=2)

        return default_config

    def _signal_handler(self, signum, frame):
        """Handle shutdown signals gracefully."""
        self.logger.info(f"Received signal {signum}. Shutting down gracefully...")
        self.stop()
        sys.exit(0)

    def start(self):
        """Start the main trading system."""
        if self.is_running:
            self.logger.warning("System is already running")
            return

        self.logger.info("Starting Self-Improving Trading System...")
        self.is_running = True
        self.system_metrics["start_time"] = datetime.now().isoformat()

        # Start the main system loop in a separate thread
        self.system_thread = threading.Thread(target=self._main_loop, daemon=True)
        self.system_thread.start()

        # Schedule regular tasks
        self._schedule_tasks()

        # Run initial startup sequence
        self._startup_sequence()

        self.logger.info("Trading system started successfully")

    def stop(self):
        """Stop the main trading system."""
        self.logger.info("Stopping trading system...")
        self.is_running = False

        # Wait for system thread to finish
        if self.system_thread and self.system_thread.is_alive():
            self.system_thread.join(timeout=10)

        self.logger.info("Trading system stopped")

    def _schedule_tasks(self):
        """Schedule regular system tasks."""
        # Strategy research every N hours
        research_interval = self.config.get("research_interval_hours", 6)
        schedule.every(research_interval).hours.do(self._run_research_cycle)

        # Performance optimization every N hours
        optimization_interval = self.config.get("optimization_interval_hours", 12)
        schedule.every(optimization_interval).hours.do(self._run_optimization_cycle)

        # Health check every N minutes
        health_interval = self.config.get("health_check_interval_minutes", 30)
        schedule.every(health_interval).minutes.do(self._health_check)

        # Daily reset at midnight
        schedule.every().day.at("00:00").do(self._daily_reset)

        self.logger.info(f"Scheduled tasks: research every {research_interval}h, "
                        f"optimization every {optimization_interval}h, "
                        f"health check every {health_interval}m")

    def _main_loop(self):
        """Main system loop that runs scheduled tasks."""
        self.logger.info("Main loop started")

        while self.is_running:
            try:
                schedule.run_pending()
                time.sleep(30)  # Check every 30 seconds
            except Exception as e:
                self.logger.error(f"Error in main loop: {e}")
                time.sleep(60)  # Wait longer on error

        self.logger.info("Main loop ended")

    def _startup_sequence(self):
        """Run initial startup tasks."""
        self.logger.info("Running startup sequence...")

        try:
            # Test MT5 connection
            if not connect():
                self.logger.error("Failed to connect to MT5")
                return

            # Check symbols availability
            available_symbols = []
            for symbol in self.symbols:
                if check_symbol(symbol):
                    available_symbols.append(symbol)
                else:
                    self.logger.warning(f"Symbol {symbol} not available")

            self.symbols = available_symbols
            if not self.symbols:
                self.logger.error("No symbols available for trading")
                return

            self.logger.info(f"Available symbols: {self.symbols}")

            # Run initial session analysis for each symbol
            for symbol in self.symbols[:2]:  # Limit to first 2 symbols to avoid overload
                self.logger.info(f"Running initial session analysis for {symbol}")
                try:
                    session_result = self.session_analyzer.analyze_intraday_patterns(symbol, months=1)
                    if "error" not in session_result:
                        self.logger.info(f"Session analysis complete for {symbol}")
                    else:
                        self.logger.warning(f"Session analysis failed for {symbol}: {session_result.get('error')}")
                except Exception as e:
                    self.logger.error(f"Error in session analysis for {symbol}: {e}")

            disconnect()
            self.logger.info("Startup sequence completed")

        except Exception as e:
            self.logger.error(f"Error in startup sequence: {e}")
            try:
                disconnect()
            except:
                pass

    def _run_research_cycle(self):
        """Run a strategy research cycle."""
        if not self.is_running:
            return

        self.logger.info("Starting strategy research cycle...")
        start_time = datetime.now()

        try:
            # Connect to MT5
            if not connect():
                self.logger.error("Failed to connect to MT5 for research")
                return

            # Run research on each symbol
            research_results = {}
            for symbol in self.symbols:
                self.logger.info(f"Researching strategies for {symbol}")
                try:
                    result = self.strategy_researcher.research_and_test_strategies(
                        symbol=symbol,
                        months=2,
                        max_strategies=8
                    )
                    research_results[symbol] = result

                    successful = result.get("successful_strategies", 0)
                    tested = result.get("strategies_tested", 0)
                    self.logger.info(f"{symbol}: {successful}/{tested} strategies successful")

                except Exception as e:
                    self.logger.error(f"Error researching {symbol}: {e}")
                    research_results[symbol] = {"error": str(e)}

            # Disconnect from MT5
            disconnect()

            # Update metrics
            self.system_metrics["total_research_cycles"] += 1
            self.last_research_time = datetime.now()

            # Log summary
            total_tested = sum(r.get("strategies_tested", 0) for r in research_results.values()
                             if isinstance(r, dict) and "strategies_tested" in r)
            total_successful = sum(r.get("successful_strategies", 0) for r in research_results.values()
                                 if isinstance(r, dict) and "successful_strategies" in r)

            self.logger.info(f"Research cycle completed: {total_successful}/{total_tested} strategies successful")
            self.logger.info(f"Research cycle duration: {(datetime.now() - start_time).total_seconds():.1f} seconds")

        except Exception as e:
            self.logger.error(f"Error in research cycle: {e}")
            try:
                disconnect()
            except:
                pass

    def _run_optimization_cycle(self):
        """Run a performance optimization cycle."""
        if not self.is_running:
            return

        self.logger.info("Starting performance optimization cycle...")
        start_time = datetime.now()

        try:
            # Run self-improvement cycle
            result = self.performance_optimizer.run_self_improvement_cycle(
                symbols=self.symbols,
                lookback_days=7
            )

            if result.get("status") == "complete":
                self.system_metrics["successful_optimizations"] += 1
                self.logger.info(f"Optimization cycle completed successfully")
                self.logger.info(f"Cycle time: {result.get('cycle_time_seconds', 0):.1f} seconds")
            else:
                self.logger.error(f"Optimization cycle failed: {result.get('message')}")

            self.logger.info(f"Optimization cycle duration: {(datetime.now() - start_time).total_seconds():.1f} seconds")

        except Exception as e:
            self.logger.error(f"Error in optimization cycle: {e}")

    def _health_check(self):
        """Perform system health check."""
        if not self.is_running:
            return

        try:
            self.logger.debug("Performing health check...")

            # Check MT5 connection
            mt5_connected = False
            try:
                if connect():
                    mt5_connected = True
                    disconnect()
            except:
                pass

            # Check system components
            components_status = {
                "strategy_researcher": "ok",
                "execution_manager": "ok",
                "performance_optimizer": "ok",
                "mt5_connection": "ok" if mt5_connected else "failed",
                "is_running": self.is_running
            }

            # Update metrics
            self.system_metrics["last_health_check"] = datetime.now().isoformat()

            # Log any issues
            if not mt5_connected:
                self.logger.warning("MT5 connection failed in health check")

            self.logger.debug("Health check completed")

        except Exception as e:
            self.logger.error(f"Error in health check: {e}")

    def _daily_reset(self):
        """Perform daily reset tasks."""
        if not self.is_running:
            return

        try:
            self.logger.info("Performing daily reset...")

            # Reset execution manager daily metrics
            self.execution_manager.reset_daily_metrics()

            # Log daily summary
            self.logger.info("Daily reset completed")

        except Exception as e:
            self.logger.error(f"Error in daily reset: {e}")

    def get_system_status(self) -> Dict:
        """Get comprehensive system status."""
        try:
            # Get status from all components
            strategy_status = {
                "knowledge_base_symbols": len(self.strategy_researcher.knowledge_base.get("symbols", {})),
                "total_strategies_tested": self.strategy_researcher.knowledge_base.get("performance_stats", {}).get("total_strategies_tested", 0),
                "successful_strategies": self.strategy_researcher.knowledge_base.get("performance_stats", {}).get("successful_strategies", 0),
                "success_rate": self.strategy_researcher.knowledge_base.get("performance_stats", {}).get("success_rate", 0.0)
            }

            execution_status = self.execution_manager.get_status()

            performance_status = self.performance_optimizer.get_system_status()

            # System uptime
            uptime = None
            if self.system_metrics["start_time"]:
                start_time = datetime.fromisoformat(self.system_metrics["start_time"])
                uptime_seconds = (datetime.now() - start_time).total_seconds()
                uptime = str(timedelta(seconds=int(uptime_seconds)))

            status = {
                "system": {
                    "is_running": self.is_running,
                    "uptime": uptime,
                    "start_time": self.system_metrics["start_time"],
                    "total_research_cycles": self.system_metrics["total_research_cycles"],
                    "successful_optimizations": self.system_metrics["successful_optimizations"],
                    "last_research": self.last_research_time.isoformat() if self.last_research_time else None,
                    "symbols": self.symbols
                },
                "components": {
                    "strategy_researcher": strategy_status,
                    "execution_manager": execution_status,
                    "performance_optimizer": performance_status
                },
                "configuration": self.config
            }

            return status

        except Exception as e:
            self.logger.error(f"Error getting system status: {e}")
            return {"error": str(e)}

    def run_manual_research(self, symbol: str = None, months: int = 2):
        """Manually run research on a symbol."""
        symbol = symbol or self.symbols[0] if self.symbols else "EURUSD"
        self.logger.info(f"Running manual research for {symbol}")

        try:
            if not connect():
                return {"error": "Failed to connect to MT5"}

            result = self.strategy_researcher.research_and_test_strategies(
                symbol=symbol,
                months=months,
                max_strategies=10
            )

            disconnect()
            return result

        except Exception as e:
            try:
                disconnect()
            except:
                pass
            return {"error": str(e)}

    def run_manual_optimization(self, lookback_days: int = 7):
        """Manually run optimization cycle."""
        self.logger.info("Running manual optimization cycle")
        return self.performance_optimizer.run_self_improvement_cycle(
            symbols=self.symbols,
            lookback_days=lookback_days
        )


def main():
    """Main entry point for the trading system."""
    import argparse

    parser = argparse.ArgumentParser(description="Self-Improving Trading System")
    parser.add_argument("--mode", choices=["start", "stop", "status", "research", "optimize"],
                       default="status", help="Operation mode")
    parser.add_argument("--symbol", type=str, help="Symbol for research/optimization")
    parser.add_argument("--months", type=int, default=2, help="Months of data for research")
    parser.add_argument("--lookback", type=int, default=7, help="Days of lookback for optimization")
    parser.add_argument("--config", type=str, default="trading_system_config.json",
                       help="Configuration file path")

    args = parser.parse_args()

    # Initialize the trading system
    trading_system = MainTradingSystem(config_file=args.config)

    if args.mode == "start":
        trading_system.start()
        try:
            # Keep the main thread alive
            while trading_system.is_running:
                time.sleep(1)
        except KeyboardInterrupt:
            trading_system.stop()

    elif args.mode == "stop":
        trading_system.stop()

    elif args.mode == "status":
        status = trading_system.get_system_status()
        print(json.dumps(status, indent=2, default=str))

    elif args.mode == "research":
        result = trading_system.run_manual_research(symbol=args.symbol, months=args.months)
        print(json.dumps(result, indent=2, default=str))

    elif args.mode == "optimize":
        result = trading_system.run_manual_optimization(lookback_days=args.lookback)
        print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()