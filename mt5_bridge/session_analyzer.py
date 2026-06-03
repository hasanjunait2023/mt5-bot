"""
Session analyzer for dynamic session optimization based on volatility and profitability patterns.
Analyzes intraday patterns to optimize trading sessions automatically.
"""

import argparse
import sys
import json
import numpy as np
import pandas as pd
import MetaTrader5 as mt5
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional, Any
import warnings
warnings.filterwarnings('ignore')

from mt5_bridge import connect, disconnect, fetch_ohlcv, get_pip_size, check_symbol
from config import SYMBOL_CONFIG, DEFAULT_PARAMS
from backtest import (
    add_indicators, compute_signals, simulate_trades, compute_metrics
)


class SessionAnalyzer:
    """Analyzes and optimizes trading sessions based on historical performance."""

    def __init__(self):
        self.session_profiles = {}

    def analyze_intraday_patterns(self, symbol: str, months: int = 6) -> Dict:
        """Analyze intraday patterns of volatility, win rate, and profitability."""
        print(f"Analyzing intraday patterns for {symbol} over {months} months...")

        if not connect():
            return {"error": "Failed to connect to MT5"}

        bars = months * 30 * 24 * 60  # Approximate M1 bars
        df = fetch_ohlcv(symbol, mt5.TIMEFRAME_M1, bars)
        disconnect()

        if df.empty:
            return {"error": "No data fetched"}

        print(f"Got {len(df)} bars from {df.index[0]} to {df.index[-1]}")

        # Add basic indicators needed for analysis
        df = add_indicators(df, DEFAULT_PARAMS)
        df = df.dropna()

        if df.empty:
            return {"error": "No data after indicators"}

        # Get pip size
        pip_size = get_pip_size(symbol)

        # Analyze each hour of the day
        hourly_stats = {}
        for hour in range(24):
            hour_data = df[df.index.hour == hour]
            if len(hour_data) < 30:  # Need minimum data points
                continue

            # Generate signals for this hour's data
            sym_cfg = SYMBOL_CONFIG.get(symbol, SYMBOL_CONFIG["EURUSD"])
            session_hours = [(hour, hour + 1)]  # Just this hour
            signals = compute_signals(hour_data, DEFAULT_PARAMS, pip_size, session_hours=session_hours)

            # Simulate trades
            trades = simulate_trades(hour_data, signals, DEFAULT_PARAMS, pip_size)

            # Calculate metrics
            if not trades.empty:
                metrics = compute_metrics(trades, DEFAULT_PARAMS["InitialBalance"])
                hourly_stats[hour] = {
                    "trades": len(trades),
                    "win_rate": metrics.get("win_rate_pct", 0),
                    "profit_factor": metrics.get("profit_factor", 0),
                    "avg_pnl_per_trade": metrics.get("net_pnl", 0) / max(len(trades), 1),
                    "total_pnl": metrics.get("net_pnl", 0),
                    "max_drawdown": metrics.get("max_drawdown_pct", 0),
                    "sharpe_ratio": metrics.get("sharpe_ratio", 0),
                    "volatility": hour_data["atr"].mean() / pip_size if "atr" in hour_data.columns else 0
                }
            else:
                hourly_stats[hour] = {
                    "trades": 0,
                    "win_rate": 0,
                    "profit_factor": 0,
                    "avg_pnl_per_trade": 0,
                    "total_pnl": 0,
                    "max_drawdown": 0,
                    "sharpe_ratio": 0,
                    "volatility": hour_data["atr"].mean() / pip_size if "atr" in hour_data.columns else 0
                }

        # Find optimal sessions based on multiple criteria
        optimal_sessions = self._find_optimal_sessions(hourly_stats)

        # Analyze session combinations (pairs of sessions that work well together)
        session_pairs = self._analyze_session_pairs(hourly_stats)

        # Analyze volatility regimes
        volatility_regimes = self._analyze_volatility_regimes(df, pip_size)

        return {
            "symbol": symbol,
            "analysis_period": {
                "start": df.index[0].isoformat(),
                "end": df.index[-1].isoformat(),
                "months": months
            },
            "hourly_stats": hourly_stats,
            "optimal_sessions": optimal_sessions,
            "best_session_pairs": session_pairs,
            "volatility_regimes": volatility_regimes,
            "recommended_session_hours": self._generate_recommendations(hourly_stats, optimal_sessions, session_pairs)
        }

    def _find_optimal_sessions(self, hourly_stats: Dict) -> List[Dict]:
        """Find optimal trading sessions based on multiple performance metrics."""
        # Filter hours with minimum trading activity
        active_hours = {h: stats for h, stats in hourly_stats.items() if stats["trades"] >= 5}

        if not active_hours:
            return []

        # Score each hour based on multiple factors
        scored_hours = []
        for hour, stats in active_hours.items():
            # Normalize metrics to 0-1 scale for scoring
            wr_score = min(stats["win_rate"] / 80, 1.0)  # Cap at 80% win rate
            pf_score = min(stats["profit_factor"] / 2.0, 1.0)  # Cap at 2.0 profit factor
            sharpe_score = max(0, min((stats["sharpe_ratio"] + 1) / 3, 1.0))  # Sharpe from -1 to 2
            dd_score = max(0, 1 - (stats["max_drawdown"] / 30))  # Penalize drawdown over 30%
            trade_score = min(stats["trades"] / 50, 1.0)  # Cap at 50 trades for score

            # Weighted composite score
            composite_score = (
                0.30 * wr_score +
                0.25 * pf_score +
                0.20 * sharpe_score +
                0.15 * dd_score +
                0.10 * trade_score
            )

            scored_hours.append({
                "hour": hour,
                "score": composite_score,
                "win_rate": stats["win_rate"],
                "profit_factor": stats["profit_factor"],
                "sharpe_ratio": stats["sharpe_ratio"],
                "max_drawdown": stats["max_drawdown"],
                "trades": stats["trades"],
                "avg_pnl_per_trade": stats["avg_pnl_per_trade"],
                "total_pnl": stats["total_pnl"]
            })

        # Sort by score descending
        scored_hours.sort(key=lambda x: x["score"], reverse=True)
        return scored_hours

    def _analyze_session_pairs(self, hourly_stats: Dict) -> List[Dict]:
        """Analyze pairs of sessions that might work well together."""
        if len(hourly_stats) < 2:
            return []

        # Look at combinations of 2-4 hour sessions
        best_pairs = []

        hours = list(hourly_stats.keys())
        for i, hour1 in enumerate(hours):
            for hour2 in hours[i+1:]:
                # Combine the hours' data conceptually
                combined_trades = hourly_stats[hour1]["trades"] + hourly_stats[hour2]["trades"]
                if combined_trades < 10:  # Need minimum combined trades
                    continue

                # Weighted average of metrics
                total_weight = combined_trades
                if total_weight == 0:
                    continue

                avg_win_rate = (hourly_stats[hour1]["win_rate"] * hourly_stats[hour1]["trades"] +
                               hourly_stats[hour2]["win_rate"] * hourly_stats[hour2]["trades"]) / total_weight

                avg_profit_factor = (hourly_stats[hour1]["profit_factor"] * hourly_stats[hour1]["trades"] +
                                    hourly_stats[hour2]["profit_factor"] * hourly_stats[hour2]["trades"]) / total_weight

                avg_sharpe = (hourly_stats[hour1]["sharpe_ratio"] * hourly_stats[hour1]["trades"] +
                             hourly_stats[hour2]["sharpe_ratio"] * hourly_stats[hour2]["trades"]) / total_weight

                avg_dd = (hourly_stats[hour1]["max_drawdown"] * hourly_stats[hour1]["trades"] +
                         hourly_stats[hour2]["max_drawdown"] * hourly_stats[hour2]["trades"]) / total_weight

                total_pnl = hourly_stats[hour1]["total_pnl"] + hourly_stats[hour2]["total_pnl"]

                # Combined score
                wr_score = min(avg_win_rate / 80, 1.0)
                pf_score = min(avg_profit_factor / 2.0, 1.0)
                sharpe_score = max(0, min((avg_sharpe + 1) / 3, 1.0))
                dd_score = max(0, 1 - (avg_dd / 30))
                trade_score = min(combined_trades / 100, 1.0)

                composite_score = (
                    0.30 * wr_score +
                    0.25 * pf_score +
                    0.20 * sharpe_score +
                    0.15 * dd_score +
                    0.10 * trade_score
                )

                best_pairs.append({
                    "sessions": [(hour1, hour1+1), (hour2, hour2+1)],
                    "score": composite_score,
                    "win_rate": avg_win_rate,
                    "profit_factor": avg_profit_factor,
                    "sharpe_ratio": avg_sharpe,
                    "max_drawdown": avg_dd,
                    "total_trades": combined_trades,
                    "total_pnl": total_pnl
                })

        # Sort by score and return top pairs
        best_pairs.sort(key=lambda x: x["score"], reverse=True)
        return best_pairs[:10]  # Top 10 pairs

    def _analyze_volatility_regimes(self, df: pd.DataFrame, pip_size: float) -> Dict:
        """Analyze different volatility regimes and their performance."""
        if "atr" not in df.columns:
            return {"error": "ATR data not available"}

        # Calculate hourly volatility
        df["hour"] = df.index.hour
        df["atr_pips"] = df["atr"] / pip_size

        volatility_stats = {}
        for hour in range(24):
            hour_data = df[df["hour"] == hour]
            if len(hour_data) < 10:
                continue

            # Volatility percentiles for this hour
            vol_25 = hour_data["atr_pips"].quantile(0.25)
            vol_50 = hour_data["atr_pips"].quantile(0.50)
            vol_75 = hour_data["atr_pips"].quantile(0.75)

            volatility_stats[hour] = {
                "mean_volatility": hour_data["atr_pips"].mean(),
                "median_volatility": vol_50,
                "volatility_25pct": vol_25,
                "volatility_75pct": vol_75,
                "volatility_range": hour_data["atr_pips"].max() - hour_data["atr_pips"].min()
            }

        return volatility_stats

    def _generate_recommendations(self, hourly_stats: Dict, optimal_sessions: List,
                                session_pairs: List) -> Dict:
        """Generate session recommendations based on analysis."""
        recommendations = {
            "primary_sessions": [],
            "secondary_sessions": [],
            "avoid_sessions": [],
            "volatility_based": {}
        }

        if not optimal_sessions:
            return recommendations

        # Primary sessions (top scoring)
        top_sessions = optimal_sessions[:3]  # Top 3
        for session in top_sessions:
            recommendations["primary_sessions"].append({
                "hour": session["hour"],
                "score": session["score"],
                "expected_win_rate": session["win_rate"],
                "expected_profit_factor": session["profit_factor"],
                "rationale": f"Highest composite score ({session['score']:.3f})"
            })

        # Secondary sessions (next best)
        if len(optimal_sessions) > 3:
            secondary = optimal_sessions[3:6]  # Next 3
            for session in secondary:
                recommendations["secondary_sessions"].append({
                    "hour": session["hour"],
                    "score": session["score"],
                    "expected_win_rate": session["win_rate"],
                    "expected_profit_factor": session["profit_factor"],
                    "rationale": f"Good alternative ({session['score']:.3f})"
                })

        # Sessions to avoid (lowest scoring)
        active_hours = [h for h, stats in hourly_stats.items() if stats["trades"] >= 5]
        if active_hours:
            hour_scores = [(h, hourly_stats[h]["win_rate"] * hourly_stats[h]["profit_factor"] / 100)
                          for h in active_hours]
            hour_scores.sort(key=lambda x: x[1])
            worst_hours = hour_scores[:3]  # Bottom 3
            for hour, score in worst_hours:
                recommendations["avoid_sessions"].append({
                    "hour": hour,
                    "score": score,
                    "win_rate": hourly_stats[hour]["win_rate"],
                    "rationale": f"Lowest performance score ({score:.2f})"
                })

        # Volatility-based recommendations
        # Find hours with stable, predictable volatility
        if hasattr(self, '_last_volatility_stats') and self._last_volatility_stats:
            stable_hours = []
            for hour, vol_stats in self._last_volatility_stats.items():
                if isinstance(vol_stats, dict) and "volatility_range" in vol_stats:
                    # Low volatility range indicates stability
                    if vol_stats["volatility_range"] < 10:  # Arbitrary threshold
                        stable_hours.append(hour)

            if stable_hours:
                recommendations["volatility_based"]["stable_hours"] = stable_hours[:4]

        return recommendations

    def run_analysis(self, symbol: str, months: int = 6) -> Dict:
        """Run complete session analysis."""
        result = self.analyze_intraday_patterns(symbol, months)
        self.session_profiles[symbol] = result
        return result


def main():
    parser = argparse.ArgumentParser(description="Session Analyzer for ScalpMaster HFT")
    parser.add_argument("--symbol", default="EURUSD", help="Symbol to analyze")
    parser.add_argument("--months", type=int, default=6, help="Months of data to analyze")
    parser.add_argument("--output", type=str, help="Output file to save results (JSON)")

    args = parser.parse_args()

    analyzer = SessionAnalyzer()
    result = analyzer.run_analysis(args.symbol.upper(), args.months)

    # Print summary
    print("\n" + "="*60)
    print(f"SESSION ANALYSIS RESULTS — {args.symbol.upper()}")
    print("="*60)

    if "error" in result:
        print(f"ERROR: {result['error']}")
        return

    print(f"Analysis Period: {result['analysis_period']['months']} months")
    print(f"Data Range: {result['analysis_period']['start'][:10]} to {result['analysis_period']['end'][:10]}")

    # Show optimal sessions
    optimal = result.get("optimal_sessions", [])
    if optimal:
        print(f"\nTop 5 Optimal Trading Hours:")
        for i, session in enumerate(optimal[:5]):
            print(f"  {i+1}. {session['hour']:02d}:00-{session['hour']+1:02d}:00 "
                  f"(Score: {session['score']:.3f}, WR: {session['win_rate']:.1f}%, "
                  f"PF: {session['profit_factor']:.2f}, Trades: {session['trades']})")

    # Show best session pairs
    pairs = result.get("best_session_pairs", [])
    if pairs:
        print(f"\nTop 3 Session Pairs:")
        for i, pair in enumerate(pairs[:3]):
            sessions_str = " + ".join([f"{s[0]:02d}:00-{s[1]:02d}:00" for s in pair['sessions']])
            print(f"  {i+1}. {sessions_str} "
                  f"(Score: {pair['score']:.3f}, WR: {pair['win_rate']:.1f}%, "
                  f"PF: {pair['profit_factor']:.2f}, Total Trades: {pair['total_trades']})")

    # Show recommendations
    recs = result.get("recommended_session_hours", {})
    if recs.get("primary_sessions"):
        print(f"\nRecommended Primary Sessions:")
        for session in recs["primary_sessions"]:
            print(f"  {session['hour']:02d}:00-{session['hour']+1:02d}:00 - {session['rationale']}")

    if recs.get("avoid_sessions"):
        print(f"\nSessions to Avoid:")
        for session in recs["avoid_sessions"]:
            print(f"  {session['hour']:02d}:00-{session['hour']+1:02d}:00 - {session['rationale']}")

    # Save results if requested
    if args.output:
        # Prepare for JSON serialization
        def make_serializable(obj):
            if isinstance(obj, dict):
                return {k: make_serializable(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [make_serializable(item) for item in obj]
            elif isinstance(obj, (np.integer, np.floating)):
                return float(obj)
            elif isinstance(obj, pd.Timestamp):
                return obj.isoformat()
            else:
                return obj

        serializable_result = make_serializable(result)
        with open(args.output, 'w') as f:
            json.dump(serializable_result, f, indent=2)
        print(f"\nResults saved to {args.output}")


if __name__ == "__main__":
    main()