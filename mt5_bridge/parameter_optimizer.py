"""
Advanced parameter optimizer with ML-guided search and robust optimization techniques.
Enhances the existing optimizer.py with better search algorithms and overfitting prevention.
"""

import argparse
import sys
import json
import numpy as np
import pandas as pd
from itertools import product
from typing import Dict, List, Tuple, Any, Optional
import warnings
warnings.filterwarnings('ignore')

from mt5_bridge import connect, disconnect, fetch_ohlcv, get_pip_size, check_symbol
from config import SYMBOL_CONFIG, DEFAULT_PARAMS, OPTIMIZER_GRID
from enhanced_backtest import WalkForwardAnalyzer, MLSignalEnhancer
from backtest import (
    add_indicators, compute_signals, simulate_trades, compute_metrics
)


class ParameterOptimizer:
    """Advanced parameter optimizer with multiple search strategies."""

    def __init__(self):
        self.wf_analyzer = WalkForwardAnalyzer(training_months=2, testing_months=1)
        self.ml_enhancer = MLSignalEnhancer()

    def grid_search(self, symbol: str, months: int = 6,
                   param_grid: Optional[Dict] = None,
                   use_walk_forward: bool = True) -> Dict:
        """Perform grid search parameter optimization."""
        if param_grid is None:
            param_grid = self._get_symbol_specific_grid(symbol)

        print(f"Running grid search for {symbol}...")
        print(f"Parameter grid: {param_grid}")

        # Generate all parameter combinations
        param_names = list(param_grid.keys())
        param_values = list(param_grid.values())
        param_combinations = list(product(*param_values))

        print(f"Testing {len(param_combinations)} parameter combinations...")

        best_params = None
        best_score = -float('inf')
        best_result = None
        results_history = []

        for i, combo in enumerate(param_combinations):
            if i % 50 == 0 and i > 0:
                print(f"  Progress: {i}/{len(param_combinations)} ({100*i/len(param_combinations):.1f}%)")

            params = DEFAULT_PARAMS.copy()
            for name, value in zip(param_names, combo):
                params[name] = value

            # Run backtest
            if use_walk_forward:
                result = self.wf_analyzer.analyze(symbol, params, months)
                # Use out-of-sample profit factor as score
                if "aggregate_metrics" in result and "avg_profit_factor" in result["aggregate_metrics"]:
                    score = result["aggregate_metrics"]["avg_profit_factor"]
                    # Penalize inconsistency
                    consistency = result["aggregate_metrics"].get("consistency_score", 0)
                    score = score * (0.5 + 0.5 * consistency)  # Blend PF with consistency
                else:
                    score = -float('inf')
            else:
                from backtest import run
                result = run(symbol, months, params)
                if "metrics" in result and "profit_factor" in result["metrics"]:
                    score = result["metrics"]["profit_factor"]
                    # Apply drawdown penalty
                    max_dd = result["metrics"].get("max_drawdown_pct", 100)
                    if max_dd > 20:  # Penalize high drawdown
                        score = score * max(0, 1 - (max_dd - 20) / 80)
                else:
                    score = -float('inf')

            results_history.append({
                "params": params.copy(),
                "score": score,
                "result": result
            })

            if score > best_score:
                best_score = score
                best_params = params.copy()
                best_result = result

        print(f"\nGrid search completed. Best score: {best_score:.4f}")

        return {
            "method": "grid_search",
            "symbol": symbol,
            "best_params": best_params,
            "best_score": best_score,
            "best_result": best_result,
            "total_combinations": len(param_combinations),
            "results_history": results_history[:20]  # Keep top 20 for analysis
        }

    def random_search(self, symbol: str, months: int = 6,
                     n_iterations: int = 100,
                     param_ranges: Optional[Dict] = None,
                     use_walk_forward: bool = True) -> Dict:
        """Perform random search parameter optimization."""
        if param_ranges is None:
            param_ranges = self._get_symbol_specific_ranges(symbol)

        print(f"Running random search for {symbol} ({n_iterations} iterations)...")

        best_params = None
        best_score = -float('inf')
        best_result = None
        results_history = []

        for i in range(n_iterations):
            if i % 20 == 0 and i > 0:
                print(f"  Progress: {i}/{n_iterations} ({100*i/n_iterations:.1f}%)")

            # Generate random parameters
            params = DEFAULT_PARAMS.copy()
            for param_name, (min_val, max_val, param_type) in param_ranges.items():
                if param_type == "int":
                    params[param_name] = np.random.randint(min_val, max_val + 1)
                else:  # float
                    params[param_name] = np.random.uniform(min_val, max_val)

            # Run backtest
            if use_walk_forward:
                result = self.wf_analyzer.analyze(symbol, params, months)
                if "aggregate_metrics" in result and "avg_profit_factor" in result["aggregate_metrics"]:
                    score = result["aggregate_metrics"]["avg_profit_factor"]
                    consistency = result["aggregate_metrics"].get("consistency_score", 0)
                    score = score * (0.5 + 0.5 * consistency)
                else:
                    score = -float('inf')
            else:
                from backtest import run
                result = run(symbol, months, params)
                if "metrics" in result and "profit_factor" in result["metrics"]:
                    score = result["metrics"]["profit_factor"]
                    max_dd = result["metrics"].get("max_drawdown_pct", 100)
                    if max_dd > 20:
                        score = score * max(0, 1 - (max_dd - 20) / 80)
                else:
                    score = -float('inf')

            results_history.append({
                "params": params.copy(),
                "score": score,
                "result": result
            })

            if score > best_score:
                best_score = score
                best_params = params.copy()
                best_result = result

        print(f"\nRandom search completed. Best score: {best_score:.4f}")

        return {
            "method": "random_search",
            "symbol": symbol,
            "best_params": best_params,
            "best_score": best_score,
            "best_result": best_result,
            "iterations": n_iterations,
            "results_history": results_history[:20]
        }

    def bayesian_optimization(self, symbol: str, months: int = 6,
                            n_iterations: int = 50,
                            use_walk_forward: bool = True) -> Dict:
        """Perform Bayesian optimization (simplified version)."""
        print(f"Running Bayesian optimization for {symbol} ({n_iterations} iterations)...")

        # For simplicity, we'll use random search with guided exploration
        # In a full implementation, you'd use libraries like scikit-optimize or optuna

        param_ranges = self._get_symbol_specific_ranges(symbol)

        # Start with some random points
        n_initial = min(10, n_iterations // 5)
        results = self.random_search(symbol, months, n_initial, param_ranges, use_walk_forward)

        # Then focus on promising regions (simplified)
        best_params = results["best_params"]
        best_score = results["best_score"]

        # Local search around best parameters
        for i in range(n_initial, n_iterations):
            params = DEFAULT_PARAMS.copy()

            # Add Gaussian noise to best parameters
            for param_name, (min_val, max_val, param_type) in param_ranges.items():
                if best_params and param_name in best_params:
                    best_val = best_params[param_name]
                    if param_type == "int":
                        noise = np.random.randint(-2, 3)  # Small integer noise
                        new_val = max(min_val, min(max_val, best_val + noise))
                    else:  # float
                        noise = np.random.normal(0, (max_val - min_val) * 0.1)  # 10% of range as std
                        new_val = max(min_val, min(max_val, best_val + noise))
                else:
                    # Fallback to random
                    if param_type == "int":
                        new_val = np.random.randint(min_val, max_val + 1)
                    else:
                        new_val = np.random.uniform(min_val, max_val)

                params[param_name] = new_val

            # Evaluate
            if use_walk_forward:
                result = self.wf_analyzer.analyze(symbol, params, months)
                if "aggregate_metrics" in result and "avg_profit_factor" in result["aggregate_metrics"]:
                    score = result["aggregate_metrics"]["avg_profit_factor"]
                    consistency = result["aggregate_metrics"].get("consistency_score", 0)
                    score = score * (0.5 + 0.5 * consistency)
                else:
                    score = -float('inf')
            else:
                from backtest import run
                result = run(symbol, months, params)
                if "metrics" in result and "profit_factor" in result["metrics"]:
                    score = result["metrics"]["profit_factor"]
                    max_dd = result["metrics"].get("max_drawdown_pct", 100)
                    if max_dd > 20:
                        score = score * max(0, 1 - (max_dd - 20) / 80)
                else:
                    score = -float('inf')

            if score > best_score:
                best_score = score
                best_params = params.copy()
                best_result = result

                # Update best parameters for next iteration (hill climbing)
                # In practice, you'd use proper Bayesian optimization here

        return {
            "method": "bayesian_optimization",
            "symbol": symbol,
            "best_params": best_params,
            "best_score": best_score,
            "best_result": best_result,
            "iterations": n_iterations
        }

    def ml_guided_optimization(self, symbol: str, months: int = 6,
                             n_iterations: int = 100) -> Dict:
        """Optimization guided by ML predictions of promising regions."""
        print(f"Running ML-guided optimization for {symbol}...")

        # This is a simplified version - in practice would use surrogate models
        param_ranges = self._get_symbol_specific_ranges(symbol)

        best_params = None
        best_score = -float('inf')
        best_result = None
        results_history = []

        # Collect initial random samples to train surrogate
        n_initial = 20
        initial_results = self.random_search(symbol, months, n_initial,
                                           param_ranges, use_walk_forward=False)

        # Extract features from parameter space for ML model
        X_params = []
        y_scores = []

        for result in initial_results["results_history"]:
            params = result["params"]
            # Convert parameters to feature vector
            param_vector = []
            for param_name in sorted(param_ranges.keys()):
                if param_name in params:
                    val = params[param_name]
                    min_val, max_val, _ = param_ranges[param_name]
                    # Normalize to 0-1 range
                    normalized = (val - min_val) / (max_val - min_val) if max_val > min_val else 0.5
                    param_vector.append(normalized)
                else:
                    param_vector.append(0.5)  # Default middle value

            X_params.append(param_vector)
            y_scores.append(result["score"])

        if len(X_params) > 5 and SKLEARN_AVAILABLE:
            try:
                from sklearn.ensemble import RandomForestRegressor

                # Train surrogate model
                surrogate = RandomForestRegressor(n_estimators=50, random_state=42)
                surrogate.fit(np.array(X_params), np.array(y_scores))

                # Use surrogate to guide search
                for i in range(n_initial, n_iterations):
                    # Generate candidate points
                    n_candidates = 1000
                    candidates = []

                    for _ in range(n_candidates):
                        params = DEFAULT_PARAMS.copy()
                        param_vector = []

                        for param_name, (min_val, max_val, param_type) in param_ranges.items():
                            if param_type == "int":
                                val = np.random.randint(min_val, max_val + 1)
                            else:
                                val = np.random.uniform(min_val, max_val)

                            params[param_name] = val
                            # Normalize for surrogate
                            normalized = (val - min_val) / (max_val - min_val) if max_val > min_val else 0.5
                            param_vector.append(normalized)

                        candidates.append((params, param_vector))

                    # Predict scores using surrogate
                    param_vectors = np.array([c[1] for c in candidates])
                    predicted_scores = surrogate.predict(param_vectors)

                    # Select top candidates
                    top_indices = np.argsort(predicted_scores)[-20:]  # Top 20

                    # Evaluate top candidates with actual backtest
                    for idx in top_indices:
                        params, _ = candidates[idx]

                        result = self.wf_analyzer.analyze(symbol, params, months)
                        if "aggregate_metrics" in result and "avg_profit_factor" in result["aggregate_metrics"]:
                            score = result["aggregate_metrics"]["avg_profit_factor"]
                            consistency = result["aggregate_metrics"].get("consistency_score", 0)
                            score = score * (0.5 + 0.5 * consistency)
                        else:
                            score = -float('inf')

                        if score > best_score:
                            best_score = score
                            best_params = params.copy()
                            best_result = result

                    # Retrain surrogate with new data every 20 iterations
                    if (i + 1) % 20 == 0:
                        # Add new evaluations to training set
                        # In practice, you'd properly manage the dataset
                        pass

            except Exception as e:
                print(f"ML-guided optimization encountered error: {e}")
                print("Falling back to random search...")
                return self.random_search(symbol, months, n_iterations, param_ranges, use_walk_forward=True)
        else:
            print("Scikit-learn not available or insufficient data, falling back to random search")
            return self.random_search(symbol, months, n_iterations, param_ranges, use_walk_forward=True)

        return {
            "method": "ml_guided_optimization",
            "symbol": symbol,
            "best_params": best_params,
            "best_score": best_score,
            "best_result": best_result,
            "iterations": n_iterations
        }

    def _get_symbol_specific_grid(self, symbol: str) -> Dict:
        """Get parameter grid specific to symbol."""
        # Base grid from config
        base_grid = OPTIMIZER_GRID.copy() if 'OPTIMIZER_GRID' in globals() else {
            "EMA_Fast": [5, 7, 9, 12],
            "EMA_Slow": [15, 21, 30],
            "RSI_Period": [5, 7, 9],
            "ATR_SL_Multi": [0.8, 1.0, 1.2, 1.5],
            "RequiredScore": [3, 4, 5]
        }

        # Symbol-specific adjustments
        symbol_grids = {
            "XAUUSD": {
                "ATR_SL_Multi": [0.5, 0.8, 1.0, 1.2],  # Tighter stops for gold
                "EMA_Fast": [7, 9, 12],
                "EMA_Slow": [21, 30, 50]
            },
            "BTCUSD": {
                "ATR_SL_Multi": [0.1, 0.2, 0.3, 0.5],  # Very tight stops for Bitcoin
                "EMA_Fast": [5, 8, 12],
                "EMA_Slow": [13, 21, 34],
                "RequiredScore": [4, 5, 6]  # Higher threshold for noisy crypto
            },
            "GBPUSD": {
                "ATR_SL_Multi": [0.8, 1.0, 1.2, 1.5],
                "EMA_Fast": [8, 10, 12],
                "EMA_Slow": [20, 30, 40]
            }
        }

        if symbol in symbol_grids:
            base_grid.update(symbol_grids[symbol])

        return base_grid

    def _get_symbol_specific_ranges(self, symbol: str) -> Dict:
        """Get parameter ranges for random/Bayesian search."""
        # Base ranges
        base_ranges = {
            "EMA_Fast": (5, 15, "int"),
            "EMA_Slow": (15, 50, "int"),
            "RSI_Period": (5, 14, "int"),
            "RSI_OB": (60, 80, "int"),
            "RSI_OS": (20, 40, "int"),
            "ATR_SL_Multi": (0.2, 2.0, "float"),
            "BB_Period": (15, 30, "int"),
            "BB_Deviation": (1.5, 3.0, "float"),
            "MACD_Fast": (5, 15, "int"),
            "MACD_Slow": (20, 40, "int"),
            "MACD_Signal": (5, 15, "int"),
            "MomCandles": (2, 5, "int"),
            "MinCandleBody": (0.1, 0.8, "float"),
            "RiskPerTrade": (0.5, 5.0, "float"),
            "RewardPerTrade": (1.0, 4.0, "float"),
            "MaxDrawdownPct": (10.0, 30.0, "float"),
            "RequiredScore": (2, 6, "int"),
            "RiskPct": (0.5, 5.0, "float"),
            "UseTrailingTP": (0, 1, "int"),  # Will be converted to bool
            "TrailTrigger": (0.3, 1.0, "float"),
            "TrailStep": (0.2, 1.0, "float")
        }

        # Symbol-specific adjustments
        symbol_ranges = {
            "XAUUSD": {
                "ATR_SL_Multi": (0.2, 1.5, "float"),  # Tighter stops
                "BB_Deviation": (2.0, 3.5, "float")   # Wider bands for volatility
            },
            "BTCUSD": {
                "ATR_SL_Multi": (0.05, 0.8, "float"), # Very tight stops
                "RequiredScore": (4, 8, "int"),       # Higher threshold
                "MomCandles": (3, 6, "int"),          # Need stronger momentum
                "MinCandleBody": (0.2, 0.9, "float")  # Larger body requirements
            },
            "GBPUSD": {
                "ATR_SL_Multi": (0.5, 2.0, "float"),
                "RSI_Period": (6, 12, "int")          # Smooth RSI for cable
            }
        }

        if symbol in symbol_ranges:
            base_ranges.update(symbol_ranges[symbol])

        return base_ranges


def main():
    parser = argparse.ArgumentParser(description="Advanced Parameter Optimizer for ScalpMaster HFT")
    parser.add_argument("--symbol", default="EURUSD", help="Symbol to optimize")
    parser.add_argument("--months", type=int, default=6, help="Months of data for optimization")
    parser.add_argument("--method", choices=["grid", "random", "bayesian", "ml"],
                       default="random", help="Optimization method")
    parser.add_argument("--iterations", type=int, default=100,
                       help="Number of iterations (for random/bayesian/ml methods)")
    parser.add_argument("--walk-forward", action="store_true",
                       help="Use walk-forward analysis for robust testing")
    parser.add_argument("--output", type=str, help="Output file to save results (JSON)")
    parser.add_argument("--params", type=str, help="JSON string of base parameters to start from")

    args = parser.parse_args()

    # Parse custom base parameters if provided
    base_params = DEFAULT_PARAMS.copy()
    if args.params:
        try:
            custom_params = json.loads(args.params)
            base_params.update(custom_params)
            print(f"Using custom base parameters: {list(custom_params.keys())}")
        except json.JSONDError:
            print("Error: Invalid JSON in --params parameter")
            sys.exit(1)

    # Initialize optimizer
    optimizer = ParameterOptimizer()

    # Run selected optimization method
    if args.method == "grid":
        result = optimizer.grid_search(
            symbol=args.symbol.upper(),
            months=args.months,
            use_walk_forward=args.walk_forward
        )
    elif args.method == "random":
        result = optimizer.random_search(
            symbol=args.symbol.upper(),
            months=args.months,
            n_iterations=args.iterations,
            use_walk_forward=args.walk_forward
        )
    elif args.method == "bayesian":
        result = optimizer.bayesian_optimization(
            symbol=args.symbol.upper(),
            months=args.months,
            n_iterations=args.iterations,
            use_walk_forward=args.walk_forward
        )
    elif args.method == "ml":
        result = optimizer.ml_guided_optimization(
            symbol=args.symbol.upper(),
            months=args.months,
            n_iterations=args.iterations
        )

    # Print results
    print("\n" + "="*60)
    print(f"OPTIMIZATION RESULTS — {args.symbol.upper()}")
    print("="*60)
    print(f"Method: {result['method']}")
    print(f"Best Score: {result['best_score']:.4f}")

    if result["best_params"]:
        print("\nBest Parameters:")
        # Show key parameters
        key_params = ["EMA_Fast", "EMA_Slow", "RSI_Period", "ATR_SL_Multi",
                     "RequiredScore", "RiskPerTrade", "RewardPerTrade"]
        for param in key_params:
            if param in result["best_params"]:
                print(f"  {param}: {result['best_params'][param]}")

    # Show performance metrics if available
    if "best_result" in result and result["best_result"]:
        best_result = result["best_result"]
        if "metrics" in best_result:
            metrics = best_result["metrics"]
            print(f"\nPerformance Metrics:")
            print(f"  Win Rate: {metrics.get('win_rate_pct', 0):.1f}%")
            print(f"  Profit Factor: {metrics.get('profit_factor', 0):.2f}")
            print(f"  Max Drawdown: {metrics.get('max_drawdown_pct', 0):.2f}%")
            print(f"  Sharpe Ratio: {metrics.get('sharpe_ratio', 0):.2f}")
            print(f"  Total Trades: {metrics.get('total_trades', 0)}")

    # Save results if requested
    if args.output:
        # Prepare results for JSON serialization (handle non-serializable objects)
        def make_serializable(obj):
            if isinstance(obj, dict):
                return {k: make_serializable(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [make_serializable(item) for item in obj]
            elif isinstance(obj, (np.integer, np.floating)):
                return float(obj)
            elif isinstance(obj, pd.DataFrame):
                return obj.to_dict('records')
            else:
                return obj

        serializable_result = make_serializable(result)
        with open(args.output, 'w') as f:
            json.dump(serializable_result, f, indent=2)
        print(f"\nResults saved to {args.output}")

if __name__ == "__main__":
    main()