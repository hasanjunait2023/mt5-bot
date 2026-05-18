"""
Strategy Research Agent - Autonomous strategy discovery and testing.
Discovers new trading strategies, tests them using walk-forward analysis,
and maintains a knowledge base of successful patterns.
"""

import json
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional, Any
import itertools
import copy
import os

import MetaTrader5 as mt5
from mt5_bridge import connect, disconnect, fetch_ohlcv, get_pip_size, check_symbol
from config import SYMBOL_CONFIG, DEFAULT_PARAMS
from mt5_bridge.enhanced_backtest import WalkForwardAnalyzer
from mt5_bridge.parameter_optimizer import ParameterOptimizer
from mt5_bridge.ml_enhanced_signals import MLCSignalFilter, ml_enhanced_compute_signals
from backtest import (
    add_indicators, compute_signals, simulate_trades, compute_metrics
)


class StrategyResearcher:
    """Autonomous strategy discovery and testing agent."""

    def __init__(self, knowledge_base_path: str = "trading_agents/knowledge_base.json"):
        self.knowledge_base_path = knowledge_base_path
        self.knowledge_base = self._load_knowledge_base()
        self.wf_analyzer = WalkForwardAnalyzer(training_months=2, testing_months=1)
        self.parameter_optimizer = ParameterOptimizer()
        self.discovered_strategies = []

    def _load_knowledge_base(self) -> Dict:
        """Load existing knowledge base or create new one."""
        if os.path.exists(self.knowledge_base_path):
            try:
                with open(self.knowledge_base_path, 'r') as f:
                    return json.load(f)
            except Exception as e:
                print(f"Error loading knowledge base: {e}")
                return self._create_empty_knowledge_base()
        else:
            return self._create_empty_knowledge_base()

    def _create_empty_knowledge_base(self) -> Dict:
        """Create an empty knowledge base structure."""
        return {
            "version": "1.0",
            "created": datetime.now().isoformat(),
            "last_updated": datetime.now().isoformat(),
            "symbols": {},
            "successful_strategies": [],
            "failed_strategies": [],
            "market_regimes": {},
            "performance_stats": {
                "total_strategies_tested": 0,
                "successful_strategies": 0,
                "success_rate": 0.0
            }
        }

    def _save_knowledge_base(self):
        """Save knowledge base to file."""
        self.knowledge_base["last_updated"] = datetime.now().isoformat()
        os.makedirs(os.path.dirname(self.knowledge_base_path), exist_ok=True)
        with open(self.knowledge_base_path, 'w') as f:
            json.dump(self.knowledge_base, f, indent=2)

    def generate_strategy_hypotheses(self, symbol: str, market_regime: str = "neutral") -> List[Dict]:
        """Generate strategy hypotheses based on market conditions and existing knowledge."""
        hypotheses = []

        # Base hypotheses from known successful patterns
        if symbol in self.knowledge_base["symbols"]:
            symbol_data = self.knowledge_base["symbols"][symbol]
            if "successful_patterns" in symbol_data:
                for pattern in symbol_data["successful_patterns"][-5:]:  # Last 5 successful patterns
                    hypothesis = {
                        "type": "pattern_based",
                        "description": f"Based on successful pattern: {pattern['description']}",
                        "parameters": pattern["parameters"].copy(),
                        "confidence": pattern["performance_score"] * 0.8  # Slightly lower confidence
                    }
                    hypotheses.append(hypothesis)

        # Technical indicator-based hypotheses
        ema_combinations = [
            {"EMA_Fast": 8, "EMA_Slow": 21},
            {"EMA_Fast": 9, "EMA_Slow": 30},
            {"EMA_Fast": 12, "EMA_Slow": 26},
            {"EMA_Fast": 5, "EMA_Slow": 13}
        ]

        rsi_levels = [
            {"RSI_Period": 7, "RSI_OB": 70, "RSI_OS": 30},
            {"RSI_Period": 14, "RSI_OB": 80, "RSI_OS": 20},
            {"RSI_Period": 10, "RSI_OB": 75, "RSI_OS": 25}
        ]

        # Market regime specific hypotheses
        regime_adjustments = {
            "trending": {
                "bias": "trend_following",
                "params": {"RequiredScore": 3, "ATR_SL_Multi": 1.2},
                "weight": 0.4
            },
            "ranging": {
                "bias": "mean_reversion",
                "params": {"RequiredScore": 4, "ATR_SL_Multi": 0.8},
                "weight": 0.4
            },
            "volatile": {
                "bias": "breakout",
                "params": {"RequiredScore": 5, "ATR_SL_Multi": 0.5},
                "weight": 0.2
            },
            "neutral": {
                "bias": "balanced",
                "params": {"RequiredScore": 4, "ATR_SL_Multi": 1.0},
                "weight": 0.3
            }
        }

        regime_info = regime_adjustments.get(market_regime, regime_adjustments["neutral"])

        # Generate combinations
        for ema in ema_combinations:
            for rsi in rsi_levels:
                params = DEFAULT_PARAMS.copy()
                params.update(ema)
                params.update(rsi)
                params.update(regime_info["params"])

                hypothesis = {
                    "type": "technical_combination",
                    "description": f"EMA{ema['EMA_Fast']}/{ema['EMA_Slow']} + RSI{rsi['RSI_Period']} ({regime_info['bias']} bias)",
                    "parameters": params.copy(),
                    "confidence": regime_info["weight"] * 0.7
                }
                hypotheses.append(hypothesis)

        # Mean reversion hypotheses (Bollinger Bands focused)
        bb_hypotheses = [
            {
                "type": "mean_reversion_bb",
                "description": "BB touch + RSI extreme + momentum confirmation",
                "parameters": {
                    **DEFAULT_PARAMS.copy(),
                    "BB_Period": 20,
                    "BB_Deviation": 2.0,
                    "RequiredScore": 5,
                    "RSI_Period": 7,
                    "RSI_OB": 75,
                    "RSI_OS": 25,
                    "MomCandles": 2,
                    "MinCandleBody": 0.3
                },
                "confidence": 0.6
            }
        ]
        hypotheses.extend(bb_hypotheses)

        # Breakout hypotheses
        breakout_hypotheses = [
            {
                "type": "breakout_momentum",
                "description": "Price breakout + volume surge + EMA alignment",
                "parameters": {
                    **DEFAULT_PARAMS.copy(),
                    "EMA_Fast": 9,
                    "EMA_Slow": 21,
                    "RequiredScore": 4,
                    "MomCandles": 3,
                    "MinCandleBody": 0.5,
                    "RiskPerTrade": 1.0,
                    "RewardPerTrade": 2.5  # Higher RR for breakouts
                },
                "confidence": 0.5
            }
        ]
        hypotheses.extend(breakout_hypotheses)

        # Sort by confidence
        hypotheses.sort(key=lambda x: x["confidence"], reverse=True)
        return hypotheses[:20]  # Return top 20 hypotheses

    def detect_market_regime(self, symbol: str, lookback_bars: int = 500) -> str:
        """Detect current market regime for strategy selection."""
        try:
            if not connect():
                return "neutral"

            df = fetch_ohlcv(symbol, mt5.TIMEFRAME_M1, lookback_bars)
            disconnect()

            if df.empty or len(df) < 50:
                return "neutral"

            # Add indicators for regime detection
            df = add_indicators(df, DEFAULT_PARAMS)
            df = df.dropna()

            if df.empty:
                return "neutral"

            # Calculate regime indicators
            # Trend strength: ADX-like measure
            df['trend_strength'] = np.abs(df['ema_fast'] - df['ema_slow']) / df['atr'].replace(0, np.nan)
            avg_trend_strength = df['trend_strength'].rolling(20).mean().iloc[-1]

            # Volatility regime
            vol_ratio = df['atr'].iloc[-1] / df['atr'].rolling(50).mean().iloc[-1]

            # RSI extremity (for ranging detection)
            rsi_extreme = ((df['rsi'] > 70) | (df['rsi'] < 30)).rolling(20).mean().iloc[-1]

            # Determine regime
            if avg_trend_strength > 1.2 and vol_ratio < 1.5:
                regime = "trending"
            elif avg_trend_strength < 0.8 and rsi_extreme > 0.3:
                regime = "ranging"
            elif vol_ratio > 2.0:
                regime = "volatile"
            else:
                regime = "neutral"

            return regime

        except Exception as e:
            print(f"Error detecting market regime: {e}")
            return "neutral"

    def test_strategy(self, symbol: str, params: Dict, months: int = 3,
                     use_walk_forward: bool = True) -> Dict:
        """Test a strategy using walk-forward analysis or standard backtest."""
        try:
            if use_walk_forward:
                result = self.wf_analyzer.analyze(symbol, params, months)
                if "aggregate_metrics" in result:
                    metrics = result["aggregate_metrics"]
                    success_score = (
                        metrics.get("avg_profit_factor", 0) *
                        metrics.get("consistency_score", 0.5)
                    )
                else:
                    return {"error": "Walk-forward analysis failed", "success": False}
            else:
                from backtest import run
                result = run(symbol, months, params)
                if "metrics" in result:
                    metrics = result["metrics"]
                    # Score based on profit factor with drawdown penalty
                    pf = metrics.get("profit_factor", 0)
                    max_dd = metrics.get("max_drawdown_pct", 100)
                    dd_penalty = max(0, 1 - (max_dd - 10) / 40) if max_dd > 10 else 1.0
                    success_score = pf * dd_penalty
                else:
                    return {"error": "Backtest failed", "success": False}

            # Determine if strategy is successful
            success_threshold = 1.2  # Minimum profit factor adjusted for consistency
            is_successful = success_score >= success_threshold

            test_result = {
                "symbol": symbol,
                "parameters": params.copy(),
                "test_period_months": months,
                "test_method": "walk_forward" if use_walk_forward else "standard",
                "metrics": metrics,
                "success_score": success_score,
                "is_successful": is_successful,
                "tested_at": datetime.now().isoformat()
            }

            if use_walk_forward and "window_results" in result:
                test_result["walk_forward_details"] = {
                    "windows": result["windows"],
                    "consistency": result["aggregate_metrics"].get("consistency_score", 0)
                }

            return test_result

        except Exception as e:
            return {
                "error": str(e),
                "success": False,
                "symbol": symbol,
                "parameters": params.copy(),
                "tested_at": datetime.now().isoformat()
            }

    def research_and_test_strategies(self, symbol: str, months: int = 3,
                                   max_strategies: int = 10) -> Dict:
        """Main research cycle: detect regime, generate hypotheses, test strategies."""
        print(f"Starting strategy research for {symbol}...")

        # Detect current market regime
        regime = self.detect_market_regime(symbol)
        print(f"Detected market regime: {regime}")

        # Generate strategy hypotheses
        hypotheses = self.generate_strategy_hypotheses(symbol, regime)
        print(f"Generated {len(hypotheses)} strategy hypotheses")

        # Test strategies
        results = []
        successful_count = 0

        for i, hypothesis in enumerate(hypotheses[:max_strategies]):
            print(f"Testing strategy {i+1}/{min(len(hypotheses), max_strategies)}: {hypothesis['description']}")

            test_result = self.test_strategy(
                symbol,
                hypothesis["parameters"],
                months=months,
                use_walk_forward=True
            )

            # Combine hypothesis and test results
            combined_result = {
                **hypothesis,
                **test_result
            }

            results.append(combined_result)

            if test_result.get("is_successful", False):
                successful_count += 1
                print(f"  ✓ SUCCESSFUL - Score: {test_result.get('success_score', 0):.3f}")
            else:
                print(f"  ✗ FAILED - Score: {test_result.get('success_score', 0):.3f}")

        # Update knowledge base
        self._update_knowledge_base(symbol, regime, results)

        # Summary
        success_rate = successful_count / len(results) if results else 0
        print(f"\nResearch Complete:")
        print(f"  Strategies tested: {len(results)}")
        print(f"  Successful strategies: {successful_count}")
        print(f"  Success rate: {success_rate:.1%}")

        return {
            "symbol": symbol,
            "market_regime": regime,
            "strategies_tested": len(results),
            "successful_strategies": successful_count,
            "success_rate": success_rate,
            "results": results,
            "best_strategy": max(results, key=lambda x: x.get("success_score", 0)) if results else None
        }

    def _update_knowledge_base(self, symbol: str, regime: str, results: List[Dict]):
        """Update knowledge base with research results."""
        # Update symbol-specific data
        if symbol not in self.knowledge_base["symbols"]:
            self.knowledge_base["symbols"][symbol] = {
                "first_seen": datetime.now().isoformat(),
                "successful_patterns": [],
                "failed_patterns": [],
                "regime_performance": {}
            }

        symbol_data = self.knowledge_base["symbols"][symbol]

        # Add successful strategies to knowledge base
        for result in results:
            if result.get("is_successful", False):
                strategy_record = {
                    "discovered_at": result["tested_at"],
                    "market_regime": regime,
                    "description": result["description"],
                    "parameters": result["parameters"],
                    "performance_score": result.get("success_score", 0),
                    "metrics": result.get("metrics", {}),
                    "type": result["type"]
                }

                # Avoid duplicates (simple check based on parameters)
                is_duplicate = False
                for existing in symbol_data["successful_patterns"]:
                    if self._parameters_similar(existing["parameters"], result["parameters"]):
                        is_duplicate = True
                        # Update if new one is better
                        if result.get("success_score", 0) > existing["performance_score"]:
                            existing.update(strategy_record)
                        break

                if not is_duplicate:
                    symbol_data["successful_patterns"].append(strategy_record)

            else:
                # Record failed strategies (keep only recent ones)
                failed_record = {
                    "tested_at": result["tested_at"],
                    "market_regime": regime,
                    "description": result["description"],
                    "parameters": result["parameters"],
                    "failure_reason": result.get("error", "Low performance score"),
                    "performance_score": result.get("success_score", 0),
                    "type": result["type"]
                }

                symbol_data["failed_patterns"].append(failed_record)

        # Keep only recent patterns (last 50 each)
        symbol_data["successful_patterns"] = symbol_data["successful_patterns"][-50:]
        symbol_data["failed_patterns"] = symbol_data["failed_patterns"][-50:]

        # Update regime performance
        if regime not in symbol_data["regime_performance"]:
            symbol_data["regime_performance"][regime] = []

        regime_results = [r for r in results if r.get("market_regime") == regime]
        successful_in_regime = [r for r in regime_results if r.get("is_successful", False)]

        regime_perf = {
            "last_updated": datetime.now().isoformat(),
            "strategies_tested": len(regime_results),
            "successful_strategies": len(successful_in_regime),
            "success_rate": len(successful_in_regime) / max(len(regime_results), 1),
            "avg_performance": np.mean([r.get("success_score", 0) for r in successful_in_regime]) if successful_in_regime else 0
        }

        symbol_data["regime_performance"][regime] = regime_perf

        # Update global stats
        newly_successful = sum(1 for r in results if r.get("is_successful", False))
        total_tested = self.knowledge_base["performance_stats"]["total_strategies_tested"] + len(results)
        total_successful = self.knowledge_base["performance_stats"]["successful_strategies"] + newly_successful
        success_rate = total_successful / max(total_tested, 1)

        self.knowledge_base["performance_stats"] = {
            "total_strategies_tested": total_tested,
            "successful_strategies": total_successful,
            "success_rate": success_rate
        }

        # Save updated knowledge base
        self._save_knowledge_base()

    def _parameters_similar(self, params1: Dict, params2: Dict, threshold: float = 0.1) -> bool:
        """Check if two parameter sets are similar (to avoid duplicates)."""
        key_params = ["EMA_Fast", "EMA_Slow", "RSI_Period", "RSI_OB", "RSI_OS",
                     "ATR_SL_Multi", "RequiredScore", "BB_Period", "BB_Deviation"]

        differences = 0
        comparisons = 0

        for param in key_params:
            if param in params1 and param in params2:
                val1, val2 = params1[param], params2[param]
                if isinstance(val1, (int, float)) and isinstance(val2, (int, float)):
                    # Normalize difference
                    max_val = max(abs(val1), abs(val2), 1)
                    if max_val > 0:
                        diff = abs(val1 - val2) / max_val
                        differences += diff
                        comparisons += 1

        if comparisons == 0:
            return False

        avg_difference = differences / comparisons
        return avg_difference < threshold

    def get_best_strategies(self, symbol: str, regime: str = None, limit: int = 5) -> List[Dict]:
        """Retrieve best strategies from knowledge base for a symbol."""
        if symbol not in self.knowledge_base["symbols"]:
            return []

        symbol_data = self.knowledge_base["symbols"][symbol]
        strategies = symbol_data.get("successful_patterns", [])

        # Filter by regime if specified
        if regime:
            strategies = [s for s in strategies if s.get("market_regime") == regime]

        # Sort by performance score
        strategies.sort(key=lambda x: x.get("performance_score", 0), reverse=True)
        return strategies[:limit]

    def run_continuous_research(self, symbols: List[str] = None, cycles: int = 3):
        """Run continuous research cycles across multiple symbols."""
        if symbols is None:
            symbols = ["EURUSD", "XAUUSD", "GBPUSD"]  # Default symbols

        print(f"Starting continuous research across {len(symbols)} symbols for {cycles} cycles...")

        all_results = {}

        for cycle in range(cycles):
            print(f"\n{'='*50}")
            print(f"RESEARCH CYCLE {cycle + 1}/{cycles}")
            print(f"{'='*50}")

            cycle_results = {}

            for symbol in symbols:
                print(f"\nResearching {symbol}...")
                result = self.research_and_test_strategies(symbol, months=2, max_strategies=8)
                cycle_results[symbol] = result

            all_results[f"cycle_{cycle+1}"] = cycle_results

            # Show cycle summary
            total_tested = sum(r["strategies_tested"] for r in cycle_results.values())
            total_successful = sum(r["successful_strategies"] for r in cycle_results.values())
            print(f"\nCycle {cycle+1} Summary:")
            print(f"  Total strategies tested: {total_tested}")
            print(f"  Total successful: {total_successful}")
            print(f"  Overall success rate: {total_successful/max(total_tested,1):.1%}")

        # Final summary
        print(f"\n{'='*50}")
        print("CONTINUOUS RESEARCH COMPLETE")
        print(f"{'='*50}")

        overall_tested = sum(
            sum(cycle["strategies_tested"] for cycle in cycle_results.values())
            for cycle_results in all_results.values()
        )
        overall_successful = sum(
            sum(cycle["successful_strategies"] for cycle in cycle_results.values())
            for cycle_results in all_results.values()
        )

        print(f"Total strategies tested across all cycles: {overall_tested}")
        print(f"Total successful strategies: {overall_successful}")
        print(f"Overall success rate: {overall_successful/max(overall_tested,1):.1%}")

        return all_results


def main():
    """Main function for running the strategy researcher."""
    import argparse
    parser = argparse.ArgumentParser(description="Strategy Research Agent")
    parser.add_argument("--symbol", type=str, help="Symbol to research (default: EURUSD)")
    parser.add_argument("--months", type=int, default=3, help="Months of data for testing")
    parser.add_argument("--max-strategies", type=int, default=10, help="Maximum strategies to test")
    parser.add_argument("--continuous", action="store_true", help="Run continuous research cycles")
    parser.add_argument("--cycles", type=int, default=3, help="Number of continuous cycles")
    parser.add_argument("--symbols", type=str, nargs='+', help="List of symbols to research")

    args = parser.parse_args()

    researcher = StrategyResearcher()

    if args.continuous:
        symbols = args.symbols if args.symbols else ["EURUSD", "XAUUSD", "GBPUSD"]
        results = researcher.run_continuous_research(symbols=symbols, cycles=args.cycles)
    else:
        symbol = args.symbol if args.symbol else "EURUSD"
        result = researcher.research_and_test_strategies(
            symbol=symbol,
            months=args.months,
            max_strategies=args.max_strategies
        )
        print(f"\nResearch completed for {symbol}")


if __name__ == "__main__":
    main()