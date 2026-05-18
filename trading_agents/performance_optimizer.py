"""
Performance Optimization Agent - Analyzes results, improves strategies, and manages self-improvement.
Continuously learns from trading performance and optimizes the overall system.
"""

import json
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional, Any
import os
import copy

from mt5_bridge import connect, disconnect, fetch_ohlcv, get_pip_size, check_symbol
from config import SYMBOL_CONFIG, DEFAULT_PARAMS
from mt5_bridge.enhanced_backtest import WalkForwardAnalyzer
from mt5_bridge.parameter_optimizer import ParameterOptimizer
from mt5_bridge.ml_enhanced_signals import MLCSignalFilter
from trading_agents.strategy_researcher import StrategyResearcher
from trading_agents.execution_manager import ExecutionManager
from backtest import (
    add_indicators, compute_signals, simulate_trades, compute_metrics
)


class PerformanceOptimizer:
    """Analyzes trading performance and manages continuous system improvement."""

    def __init__(self,
                 knowledge_base_path: str = "trading_agents/knowledge_base.json",
                 performance_log_path: str = "trading_agents/performance_log.json"):
        self.knowledge_base_path = knowledge_base_path
        self.performance_log_path = performance_log_path

        # Load knowledge base and performance log
        self.knowledge_base = self._load_knowledge_base()
        self.performance_log = self._load_performance_log()

        # Initialize components
        self.strategy_researcher = StrategyResearcher(knowledge_base_path)
        self.wf_analyzer = WalkForwardAnalyzer(training_months=2, testing_months=1)
        self.parameter_optimizer = ParameterOptimizer()

        # System performance tracking
        self.system_metrics = {
            "total_cycles": 0,
            "successful_improvements": 0,
            "avg_performance_improvement": 0.0,
            "best_performance_ever": 0.0,
            "last_optimization": None
        }

        # Adaptive parameters
        self.adaptive_parameters = {
            "exploration_rate": 0.3,  # How much to explore new strategies vs exploit known good ones
            "learning_rate": 0.1,     # How quickly to adapt to new performance data
            "risk_tolerance": 0.01,   # Base risk tolerance — fixed at 1% per trade
            "confidence_threshold": 0.6  # ML confidence threshold for signal filtering
        }

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

    def _load_performance_log(self) -> Dict:
        """Load performance log or create new one."""
        if os.path.exists(self.performance_log_path):
            try:
                with open(self.performance_log_path, 'r') as f:
                    return json.load(f)
            except Exception as e:
                print(f"Error loading performance log: {e}")
                return self._create_empty_performance_log()
        else:
            return self._create_empty_performance_log()

    def _create_empty_performance_log(self) -> Dict:
        """Create an empty performance log structure."""
        return {
            "version": "1.0",
            "created": datetime.now().isoformat(),
            "last_updated": datetime.now().isoformat(),
            "daily_performance": [],
            "weekly_performance": [],
            "monthly_performance": [],
            "system_adaptations": [],
            "benchmark_comparisons": []
        }

    def _save_knowledge_base(self):
        """Save knowledge base to file."""
        self.knowledge_base["last_updated"] = datetime.now().isoformat()
        os.makedirs(os.path.dirname(self.knowledge_base_path), exist_ok=True)
        with open(self.knowledge_base_path, 'w') as f:
            json.dump(self.knowledge_base, f, indent=2)

    def _save_performance_log(self):
        """Save performance log to file."""
        self.performance_log["last_updated"] = datetime.now().isoformat()
        os.makedirs(os.path.dirname(self.performance_log_path), exist_ok=True)
        with open(self.performance_log_path, 'w') as f:
            json.dump(self.performance_log, f, indent=2)

    def analyze_trading_performance(self, lookback_days: int = 7) -> Dict:
        """Analyze recent trading performance to identify improvement areas."""
        try:
            # In a real system, this would analyze actual trade data
            # For now, we'll simulate based on knowledge base and performance log

            recent_performance = self.performance_log.get("daily_performance", [])[-lookback_days:]

            if not recent_performance:
                # No recent performance data - return baseline analysis
                return {
                    "status": "insufficient_data",
                    "message": "No recent performance data available",
                    "recommendations": ["Collect more trading data before analysis"],
                    "performance_trend": "unknown"
                }

            # Extract key metrics
            daily_returns = [day.get("net_pnl_pct", 0) for day in recent_performance]
            win_rates = [day.get("win_rate", 0) for day in recent_performance]
            profit_factors = [day.get("profit_factor", 0) for day in recent_performance]
            max_drawdowns = [day.get("max_drawdown", 0) for day in recent_performance]

            # Calculate trends
            if len(daily_returns) >= 3:
                # Simple linear trend
                x = np.arange(len(daily_returns))
                coeffs = np.polyfit(x, daily_returns, 1)
                return_trend = coeffs[0]  # Slope

                # Win rate trend
                wr_coeffs = np.polyfit(x, win_rates, 1)
                win_rate_trend = wr_coeffs[0]

                # Profit factor trend
                pf_coeffs = np.polyfit(x, profit_factors, 1)
                profit_factor_trend = pf_coeffs[0]
            else:
                return_trend = 0.0
                win_rate_trend = 0.0
                profit_factor_trend = 0.0

            # Calculate averages
            avg_return = np.mean(daily_returns) if daily_returns else 0.0
            avg_win_rate = np.mean(win_rates) if win_rates else 0.0
            avg_profit_factor = np.mean(profit_factors) if profit_factors else 0.0
            avg_max_dd = np.mean(max_drawdowns) if max_drawdowns else 0.0

            # Identify weaknesses and strengths
            weaknesses = []
            strengths = []

            if avg_return < 0.1:  # Less than 0.1% daily return
                weaknesses.append("Low average returns")
            elif avg_return > 0.5:  # More than 0.5% daily return
                strengths.append("Strong average returns")

            if avg_win_rate < 40:  # Less than 40% win rate
                weaknesses.append("Low win rate")
            elif avg_win_rate > 60:  # More than 60% win rate
                strengths.append("High win rate")

            if avg_profit_factor < 1.2:  # Less than 1.2 profit factor
                weaknesses.append("Poor profit factor")
            elif avg_profit_factor > 1.8:  # More than 1.8 profit factor
                strengths.append("Excellent profit factor")

            if avg_max_dd > 2.0:  # More than 2% daily drawdown
                weaknesses.append("High drawdown")
            elif avg_max_dd < 1.0:  # Less than 1% daily drawdown
                strengths.append("Low drawdown")

            # Determine overall performance trend
            if return_trend > 0.05 and win_rate_trend > 0.1:
                performance_trend = "improving"
            elif return_trend < -0.05 or win_rate_trend < -0.1:
                performance_trend = "declining"
            else:
                performance_trend = "stable"

            # Generate recommendations
            recommendations = []

            if "Low average returns" in weaknesses:
                recommendations.append("Explore higher frequency strategies or better entry timing")

            if "Low win rate" in weaknesses:
                recommendations.append("Increase signal filtering rigor or adjust entry criteria")

            if "Poor profit factor" in weaknesses:
                recommendations.append("Improve risk/reward ratio or let winners run longer")

            if "High drawdown" in weaknesses:
                recommendations.append("Reduce position sizes or improve stop loss placement")

            if not recommendations:
                recommendations.append("Performance is solid - focus on fine-tuning and consistency")

            return {
                "status": "analyzed",
                "analysis_period_days": lookback_days,
                "performance_metrics": {
                    "avg_daily_return": avg_return,
                    "avg_win_rate": avg_win_rate,
                    "avg_profit_factor": avg_profit_factor,
                    "avg_max_drawdown": avg_max_dd,
                    "return_trend": return_trend,
                    "win_rate_trend": win_rate_trend,
                    "profit_factor_trend": profit_factor_trend
                },
                "weaknesses": weaknesses,
                "strengths": strengths,
                "performance_trend": performance_trend,
                "recommendations": recommendations,
                "data_points": len(recent_performance)
            }

        except Exception as e:
            return {
                "status": "error",
                "message": f"Error analyzing performance: {e}",
                "recommendations": ["Check system logs and data integrity"]
            }

    def optimize_system_parameters(self, performance_analysis: Dict) -> Dict:
        """Optimize system parameters based on performance analysis."""
        try:
            optimizations_applied = []

            # Extract performance metrics
            metrics = performance_analysis.get("performance_metrics", {})
            weaknesses = performance_analysis.get("weaknesses", [])
            strengths = performance_analysis.get("strengths", [])
            trend = performance_analysis.get("performance_trend", "stable")

            # Adapt exploration rate based on performance
            current_exploration = self.adaptive_parameters["exploration_rate"]

            if trend == "declining" or "Low average returns" in weaknesses:
                # Increase exploration when performing poorly
                new_exploration = min(0.5, current_exploration + 0.1)
                if new_exploration != current_exploration:
                    self.adaptive_parameters["exploration_rate"] = new_exploration
                    optimizations_applied.append({
                        "parameter": "exploration_rate",
                        "old_value": current_exploration,
                        "new_value": new_exploration,
                        "reason": "Poor performance - increasing exploration for new strategies"
                    })
            elif trend == "improving" and "Strong average returns" in strengths:
                # Slightly decrease exploitation when doing well to lock in gains
                new_exploration = max(0.2, current_exploration - 0.05)
                if new_exploration != current_exploration:
                    self.adaptive_parameters["exploration_rate"] = new_exploration
                    optimizations_applied.append({
                        "parameter": "exploration_rate",
                        "old_value": current_exploration,
                        "new_value": new_exploration,
                        "reason": "Good performance - slightly increasing exploitation"
                    })

            # Adjust learning rate based on volatility in performance
            return_volatility = abs(metrics.get("return_trend", 0))
            if return_volatility > 0.2:  # High volatility in returns
                new_learning_rate = min(0.2, self.adaptive_parameters["learning_rate"] + 0.05)
                if new_learning_rate != self.adaptive_parameters["learning_rate"]:
                    self.adaptive_parameters["learning_rate"] = new_learning_rate
                    optimizations_applied.append({
                        "parameter": "learning_rate",
                        "old_value": self.adaptive_parameters["learning_rate"] - 0.05,
                        "new_value": new_learning_rate,
                        "reason": "High performance volatility - increasing adaptation speed"
                    })
            elif return_volatility < 0.05:  # Very stable performance
                new_learning_rate = max(0.05, self.adaptive_parameters["learning_rate"] - 0.02)
                if new_learning_rate != self.adaptive_parameters["learning_rate"]:
                    self.adaptive_parameters["learning_rate"] = new_learning_rate
                    optimizations_applied.append({
                        "parameter": "learning_rate",
                        "old_value": self.adaptive_parameters["learning_rate"] + 0.02,
                        "new_value": new_learning_rate,
                        "reason": "Stable performance - decreasing adaptation speed to avoid overfitting"
                    })

            # Adjust risk tolerance based on drawdown
            avg_dd = metrics.get("avg_max_drawdown", 0)
            if avg_dd > 2.0:  # High drawdown
                new_risk = max(0.005, self.adaptive_parameters["risk_tolerance"] - 0.005)
                if new_risk != self.adaptive_parameters["risk_tolerance"]:
                    self.adaptive_parameters["risk_tolerance"] = new_risk
                    optimizations_applied.append({
                        "parameter": "risk_tolerance",
                        "old_value": self.adaptive_parameters["risk_tolerance"] + 0.005,
                        "new_value": new_risk,
                        "reason": "High drawdown - reducing risk tolerance"
                    })
            elif avg_dd < 0.5 and "Low drawdown" in strengths:
                # Can afford slightly more risk — but never exceed 1.5%
                new_risk = min(0.015, self.adaptive_parameters["risk_tolerance"] + 0.002)
                if new_risk != self.adaptive_parameters["risk_tolerance"]:
                    self.adaptive_parameters["risk_tolerance"] = new_risk
                    optimizations_applied.append({
                        "parameter": "risk_tolerance",
                        "old_value": self.adaptive_parameters["risk_tolerance"] - 0.005,
                        "new_value": new_risk,
                        "reason": "Low drawdown - slightly increasing risk tolerance for better returns"
                    })

            # Adjust confidence threshold based on win rate
            win_rate = metrics.get("avg_win_rate", 0)
            if win_rate < 35:  # Very low win rate
                new_confidence = min(0.8, self.adaptive_parameters["confidence_threshold"] + 0.1)
                if new_confidence != self.adaptive_parameters["confidence_threshold"]:
                    self.adaptive_parameters["confidence_threshold"] = new_confidence
                    optimizations_applied.append({
                        "parameter": "confidence_threshold",
                        "old_value": self.adaptive_parameters["confidence_threshold"] - 0.1,
                        "new_value": new_confidence,
                        "reason": "Low win rate - increasing ML confidence threshold for better signal quality"
                    })
            elif win_rate > 65:  # High win rate
                new_confidence = max(0.4, self.adaptive_parameters["confidence_threshold"] - 0.05)
                if new_confidence != self.adaptive_parameters["confidence_threshold"]:
                    self.adaptive_parameters["confidence_threshold"] = new_confidence
                    optimizations_applied.append({
                        "parameter": "confidence_threshold",
                        "old_value": self.adaptive_parameters["confidence_threshold"] + 0.05,
                        "new_value": new_confidence,
                        "reason": "High win rate - can decrease confidence threshold for more signals"
                    })

            # Log the optimizations
            adaptation_record = {
                "timestamp": datetime.now().isoformat(),
                "trigger_analysis": performance_analysis,
                "optimizations_applied": optimizations_applied,
                "adaptive_parameters_after": self.adaptive_parameters.copy()
            }

            self.performance_log["system_adaptations"].append(adaptation_record)
            # Keep only recent adaptations
            self.performance_log["system_adaptations"] = self.performance_log["system_adaptations"][-50:]

            self._save_performance_log()

            return {
                "status": "optimized",
                "optimizations_applied": optimizations_applied,
                "adaptive_parameters": self.adaptive_parameters.copy(),
                "message": f"Applied {len(optimizations_applied)} parameter optimizations"
            }

        except Exception as e:
            return {
                "status": "error",
                "message": f"Error optimizing parameters: {e}",
                "optimizations_applied": []
            }

    def generate_improvement_plan(self, performance_analysis: Dict) -> Dict:
        """Generate a concrete improvement plan based on performance analysis."""
        try:
            weaknesses = performance_analysis.get("weaknesses", [])
            strengths = performance_analysis.get("strengths", [])
            recommendations = performance_analysis.get("recommendations", [])
            trend = performance_analysis.get("performance_trend", "stable")

            improvement_plan = {
                "timestamp": datetime.now().isoformat(),
                "based_on_analysis": performance_analysis,
                "immediate_actions": [],
                "short_term_goals": [],
                "long_term_strategies": [],
                "priority_level": "medium"
            }

            # Determine priority based on performance
            if trend == "declining" or ("High drawdown" in weaknesses and "Low average returns" in weaknesses):
                improvement_plan["priority_level"] = "high"
            elif trend == "improving" and len(strengths) >= 3:
                improvement_plan["priority_level"] = "low"
            else:
                improvement_plan["priority_level"] = "medium"

            # Generate immediate actions based on weaknesses
            if "Low average returns" in weaknesses:
                improvement_plan["immediate_actions"].append({
                    "action": "Increase strategy research frequency",
                    "description": "Run additional strategy discovery cycles to find higher returning approaches",
                    "timeline": "1-2 days",
                    "owner": "Strategy Researcher"
                })

            if "Low win rate" in weaknesses:
                improvement_plan["immediate_actions"].append({
                    "action": "Enhance ML signal filtering",
                    "description": "Retrain ML models with recent data and increase confidence thresholds",
                    "timeline": "1 day",
                    "owner": "Performance Optimizer"
                })

            if "Poor profit factor" in weaknesses:
                improvement_plan["immediate_actions"].append({
                    "action": "Optimize risk/reward ratios",
                    "description": "Analyze exit strategies and adjust take profit levels",
                    "timeline": "2-3 days",
                    "owner": "Execution Manager"
                })

            if "High drawdown" in weaknesses:
                improvement_plan["immediate_actions"].append({
                    "action": "Reduce position sizes and tighten stops",
                    "description": "Immediately reduce risk per trade and review stop loss placement",
                    "timeline": "Immediate",
                    "owner": "Execution Manager"
                })

            # Short term goals (1-2 weeks)
            if "Strong average returns" in strengths:
                improvement_plan["short_term_goals"].append({
                    "goal": "Scale successful strategies",
                    "description": "Gradually increase allocation to strategies showing consistent performance",
                    "timeline": "1-2 weeks",
                    "metrics_to_improve": ["total_return", "sharpe_ratio"]
                })

            improvement_plan["short_term_goals"].append({
                "goal": "Improve strategy robustness",
                "description": "Increase walk-forward analysis windows and test across multiple market regimes",
                "timeline": "1-2 weeks",
                "metrics_to_improve": ["consistency_score", "win_rate_stability"]
            })

            # Long term strategies (1+ months)
            improvement_plan["long_term_strategies"].append({
                "strategy": "Develop regime-specific strategies",
                "description": "Create specialized strategies for different market conditions (trending, ranging, volatile)",
                "timeline": "1-3 months",
                "expected_impact": "20-40% improvement in risk-adjusted returns"
            })

            improvement_plan["long_term_strategies"].append({
                "strategy": "Implement ensemble trading",
                "description": "Combine multiple uncorrelated strategies for smoother equity curve",
                "timeline": "2-4 months",
                "expected_impact": "Reduced drawdown and improved consistency"
            })

            # If no specific actions were generated, add generic ones
            if not improvement_plan["immediate_actions"]:
                improvement_plan["immediate_actions"].append({
                    "action": "Monthly performance review and optimization",
                    "description": "Conduct comprehensive performance analysis and parameter optimization",
                    "timeline": "Monthly",
                    "owner": "Performance Optimizer"
                })

            return {
                "status": "plan_generated",
                "improvement_plan": improvement_plan
            }

        except Exception as e:
            return {
                "status": "error",
                "message": f"Error generating improvement plan: {e}",
                "improvement_plan": {}
            }

    def run_self_improvement_cycle(self, symbols: List[str] = None,
                                 lookback_days: int = 7) -> Dict:
        """Run a complete self-improvement cycle."""
        try:
            print("Starting self-improvement cycle...")
            cycle_start = datetime.now()

            # Step 1: Analyze current performance
            print("Step 1: Analyzing trading performance...")
            performance_analysis = self.analyze_trading_performance(lookback_days)

            if performance_analysis.get("status") == "error":
                return {
                    "status": "error",
                    "message": f"Performance analysis failed: {performance_analysis.get('message')}",
                    "cycle_time": (datetime.now() - cycle_start).total_seconds()
                }

            print(f"Performance Trend: {performance_analysis.get('performance_trend', 'unknown')}")
            print(f"Weaknesses: {', '.join(performance_analysis.get('weaknesses', []))}")
            print(f"Strengths: {', '.join(performance_analysis.get('strengths', []))}")

            # Step 2: Optimize system parameters
            print("\nStep 2: Optimizing system parameters...")
            optimization_result = self.optimize_system_parameters(performance_analysis)

            if optimization_result.get("status") == "error":
                print(f"Parameter optimization failed: {optimization_result.get('message')}")
            else:
                opt_count = len(optimization_result.get("optimizations_applied", []))
                print(f"Applied {opt_count} parameter optimizations")

            # Step 3: Generate improvement plan
            print("\nStep 3: Generating improvement plan...")
            plan_result = self.generate_improvement_plan(performance_analysis)

            if plan_result.get("status") == "error":
                print(f"Improvement plan generation failed: {plan_result.get('message')}")
            else:
                priority = plan_result.get("improvement_plan", {}).get("priority_level", "medium")
                print(f"Improvement plan generated with {priority} priority")

            # Step 4: Run targeted strategy research if needed
            print("\nStep 4: Running targeted strategy research...")
            research_results = {}

            # Determine which symbols to research based on performance
            if symbols is None:
                # Default to major symbols
                symbols = ["EURUSD", "XAUUSD", "GBPUSD"]

                # If we have performance data suggesting issues with specific symbols, focus there
                weaknesses = performance_analysis.get("weaknesses", [])
                if "Low average returns" in weaknesses or "Poor profit factor" in weaknesses:
                    # Add more symbols for exploration
                    symbols.extend(["USDJPY", "AUDUSD", "USDCHF"])
                symbols = list(set(symbols))  # Remove duplicates

            # Run research on each symbol (limited to avoid excessive computation)
            max_symbols_per_cycle = 3
            research_symbols = symbols[:max_symbols_per_cycle]

            for symbol in research_symbols:
                print(f"  Researching {symbol}...")
                try:
                    # Use strategy researcher to find new approaches
                    research_result = self.strategy_researcher.research_and_test_strategies(
                        symbol=symbol,
                        months=2,  # Shorter lookback for frequent updates
                        max_strategies=5  # Limited strategies per symbol
                    )
                    research_results[symbol] = research_result

                    successful = research_result.get("successful_strategies", 0)
                    tested = research_result.get("strategies_tested", 0)
                    print(f"    {symbol}: {successful}/{tested} strategies successful")

                except Exception as e:
                    print(f"    Error researching {symbol}: {e}")
                    research_results[symbol] = {"error": str(e)}

            # Step 5: Update knowledge base with new findings
            print("\nStep 5: Updating knowledge base...")
            # The strategy researcher already updates the knowledge base during research

            cycle_end = datetime.now()
            cycle_time = (cycle_end - cycle_start).total_seconds()

            # Update system metrics
            self.system_metrics["total_cycles"] += 1
            self.system_metrics["last_optimization"] = cycle_end.isoformat()

            # Check if we had successful improvements
            total_new_strategies = sum(
                r.get("successful_strategies", 0)
                for r in research_results.values()
                if isinstance(r, dict) and "successful_strategies" in r
            )

            if total_new_strategies > 0:
                self.system_metrics["successful_improvements"] += 1

            # Log the cycle
            cycle_record = {
                "timestamp": cycle_end.isoformat(),
                "cycle_duration_seconds": cycle_time,
                "performance_analysis": performance_analysis,
                "optimization_result": optimization_result,
                "plan_result": plan_result,
                "research_results": research_results,
                "system_metrics": self.system_metrics.copy()
            }

            self.performance_log["monthly_performance"].append(cycle_record)
            # Keep only recent records
            self.performance_log["monthly_performance"] = self.performance_log["monthly_performance"][-12:]

            # Save logs
            self._save_performance_log()
            self.knowledge_base["last_updated"] = datetime.now().isoformat()
            self._save_knowledge_base()

            return {
                "status": "complete",
                "cycle_time_seconds": cycle_time,
                "performance_analysis": performance_analysis,
                "optimization_result": optimization_result,
                "improvement_plan": plan_result.get("improvement_plan", {}),
                "research_results": research_results,
                "system_metrics": self.system_metrics.copy(),
                "message": f"Self-improvement cycle completed in {cycle_time:.1f} seconds"
            }

        except Exception as e:
            return {
                "status": "error",
                "message": f"Error in self-improvement cycle: {e}",
                "cycle_time": (datetime.now() - cycle_start).total_seconds() if 'cycle_start' in locals() else 0
            }

    def get_system_status(self) -> Dict:
        """Get current status of the self-improving system."""
        return {
            "system_metrics": self.system_metrics.copy(),
            "adaptive_parameters": self.adaptive_parameters.copy(),
            "knowledge_base_stats": {
                "symbols_tracked": len(self.knowledge_base.get("symbols", {})),
                "total_strategies_tested": self.knowledge_base.get("performance_stats", {}).get("total_strategies_tested", 0),
                "successful_strategies": self.knowledge_base.get("performance_stats", {}).get("successful_strategies", 0),
                "success_rate": self.knowledge_base.get("performance_stats", {}).get("success_rate", 0.0)
            },
            "recent_adaptations": self.performance_log.get("system_adaptations", [])[-5:],  # Last 5 adaptations
            "last_cycle": self.performance_log.get("monthly_performance", [])[-1] if self.performance_log.get("monthly_performance") else None
        }


def main():
    """Main function for running the performance optimizer."""
    import argparse
    parser = argparse.ArgumentParser(description="Performance Optimization Agent")
    parser.add_argument("--lookback", type=int, default=7, help="Days of performance to analyze")
    parser.add_argument("--symbols", type=str, nargs='+', help="Symbols to research")
    parser.add_argument("--cycles", type=int, default=1, help="Number of improvement cycles to run")
    parser.add_argument("--status-only", action="store_true", help="Only show system status")

    args = parser.parse_args()

    optimizer = PerformanceOptimizer()

    if args.status_only:
        status = optimizer.get_system_status()
        print(json.dumps(status, indent=2, default=str))
    else:
        results = []
        for i in range(args.cycles):
            if args.cycles > 1:
                print(f"\n{'='*60}")
                print(f"IMPROVEMENT CYCLE {i+1}/{args.cycles}")
                print(f"{'='*60}")

            result = optimizer.run_self_improvement_cycle(
                symbols=args.symbols,
                lookback_days=args.lookback
            )
            results.append(result)

            if result.get("status") == "complete":
                print(f"\nCycle {i+1} completed successfully")
                print(f"Cycle time: {result.get('cycle_time_seconds', 0):.1f} seconds")
            else:
                print(f"\nCycle {i+1} failed: {result.get('message')}")

        if args.cycles > 1:
            print(f"\n{'='*60}")
            print(f"ALL {args.cycles} CYCLES COMPLETED")
            print(f"{'='*60}")

            successful_cycles = sum(1 for r in results if r.get("status") == "complete")
            print(f"Successful cycles: {successful_cycles}/{args.cycles}")

            if successful_cycles > 0:
                avg_time = np.mean([r.get("cycle_time_seconds", 0) for r in results if r.get("status") == "complete"])
                print(f"Average cycle time: {avg_time:.1f} seconds")


if __name__ == "__main__":
    main()