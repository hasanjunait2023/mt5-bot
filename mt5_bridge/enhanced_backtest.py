"""
Enhanced backtest engine with walk-forward analysis and ML-enhanced signal filtering.
Builds upon the existing backtest.py with improved robustness and performance.
"""

import argparse
import sys
from datetime import datetime, timedelta
import numpy as np
import pandas as pd
from typing import Dict, List, Tuple, Optional, Any
import json
import os

import MetaTrader5 as mt5
from mt5_bridge import connect, disconnect, fetch_ohlcv, get_pip_size, check_symbol
from config import SYMBOL_CONFIG, DEFAULT_PARAMS
from backtest import (
    add_indicators, compute_signals, simulate_trades, compute_metrics,
    get_pip_size as bt_get_pip_size
)

# Try to import scikit-learn for ML components
try:
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.preprocessing import StandardScaler
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False
    print("Warning: scikit-learn not available. ML features will be disabled.")


class WalkForwardAnalyzer:
    """Walk-forward analysis to prevent overfitting in parameter optimization."""

    def __init__(self, training_months: int = 3, testing_months: int = 1):
        self.training_months = training_months
        self.testing_months = testing_months

    def split_data(self, df: pd.DataFrame) -> List[Tuple[pd.DataFrame, pd.DataFrame]]:
        """Split data into walk-forward windows."""
        windows = []
        total_bars = len(df)
        bars_per_month = 30 * 24 * 60  # Approximate M1 bars per month

        start_idx = 0
        while start_idx + (self.training_months * bars_per_month) + (self.testing_months * bars_per_month) <= total_bars:
            # Calculate bar indices
            train_end = start_idx + (self.training_months * bars_per_month)
            test_end = train_end + (self.testing_months * bars_per_month)

            train_df = df.iloc[start_idx:train_end].copy()
            test_df = df.iloc[train_end:test_end].copy()

            windows.append((train_df, test_df))
            start_idx = train_end  # Move forward by training period

        return windows

    def analyze(self, symbol: str, base_params: Dict, months: int = 12) -> Dict:
        """Run walk-forward analysis and return aggregated results."""
        print(f"Fetching {months} months of data for walk-forward analysis...")

        if not connect():
            return {"error": "Failed to connect to MT5"}

        bars = months * 30 * 24 * 60  # Approximate M1 bars
        df = fetch_ohlcv(symbol, mt5.TIMEFRAME_M1, bars)
        disconnect()

        if df.empty:
            return {"error": "No data fetched"}

        print(f"Got {len(df)} bars from {df.index[0]} to {df.index[-1]}")

        # Create walk-forward windows
        windows = self.split_data(df)
        print(f"Created {len(windows)} walk-forward windows")

        if not windows:
            return {"error": "Insufficient data for walk-forward analysis"}

        # Run analysis on each window
        window_results = []
        all_trades = []

        for i, (train_df, test_df) in enumerate(windows):
            print(f"\nProcessing window {i+1}/{len(windows)}")
            print(f"  Training: {train_df.index[0]} to {train_df.index[-1]}")
            print(f"  Testing:  {test_df.index[0]} to {test_df.index[-1]}")

            # Optimize parameters on training data (simplified - in practice would call optimizer)
            # For now, we'll use base params and demonstrate the framework
            params = base_params.copy()

            # Run backtest on training data (for parameter validation)
            train_result = self._run_backtest_on_data(train_df, symbol, params)

            # Run backtest on testing data (out-of-sample performance)
            test_result = self._run_backtest_on_data(test_df, symbol, params)

            window_result = {
                "window": i + 1,
                "train_period": {
                    "start": train_df.index[0].isoformat(),
                    "end": train_df.index[-1].isoformat()
                },
                "test_period": {
                    "start": test_df.index[0].isoformat(),
                    "end": test_df.index[-1].isoformat()
                },
                "train_metrics": train_result.get("metrics", {}),
                "test_metrics": test_result.get("metrics", {}),
                "train_trades": train_result.get("trades", pd.DataFrame()).to_dict('records'),
                "test_trades": test_result.get("trades", pd.DataFrame()).to_dict('records')
            }

            window_results.append(window_result)
            all_trades.extend(test_result.get("trades", pd.DataFrame()).to_dict('records'))

        # Calculate aggregate metrics
        aggregate_metrics = self._calculate_aggregate_metrics(window_results)

        return {
            "analysis_type": "walk_forward",
            "symbol": symbol,
            "windows": len(windows),
            "window_results": window_results,
            "aggregate_metrics": aggregate_metrics,
            "all_test_trades": all_trades
        }

    def _run_backtest_on_data(self, df: pd.DataFrame, symbol: str, params: Dict) -> Dict:
        """Run backtest on a dataframe and return results."""
        try:
            pip_size = get_pip_size(symbol)

            # Add indicators
            df_ind = add_indicators(df.copy(), params)
            df_ind = df_ind.dropna()

            if df_ind.empty:
                return {"error": "No data after indicators"}

            # Get symbol config
            sym_cfg = SYMBOL_CONFIG.get(symbol, SYMBOL_CONFIG["EURUSD"])
            session_hours = sym_cfg.get("session_hours")

            # Generate signals
            signals = compute_signals(df_ind, params, pip_size, session_hours=session_hours)

            # Simulate trades
            trades = simulate_trades(df_ind, signals, params, pip_size)

            # Compute metrics
            metrics = compute_metrics(trades, params["InitialBalance"])

            return {
                "metrics": metrics,
                "trades": trades,
                "symbol": symbol,
                "params": params
            }
        except Exception as e:
            return {"error": str(e)}

    def _calculate_aggregate_metrics(self, window_results: List[Dict]) -> Dict:
        """Calculate aggregate metrics across all walk-forward windows."""
        # Collect all test metrics
        test_metrics_list = [w["test_metrics"] for w in window_results if "test_metrics" in w]

        if not test_metrics_list:
            return {"error": "No valid test metrics"}

        # Calculate averages and consistency metrics
        keys = ["win_rate_pct", "profit_factor", "max_drawdown_pct", "sharpe_ratio"]
        aggregate = {}

        for key in keys:
            values = [m.get(key, 0) for m in test_metrics_list if isinstance(m.get(key, 0), (int, float))]
            if values:
                aggregate[f"avg_{key}"] = np.mean(values)
                aggregate[f"std_{key}"] = np.std(values)
                aggregate[f"min_{key}"] = np.min(values)
                aggregate[f"max_{key}"] = np.max(values)

        # Calculate consistency score (lower std dev = more consistent)
        if "std_profit_factor" in aggregate and aggregate["avg_profit_factor"] > 0:
            consistency = max(0, 1 - (aggregate["std_profit_factor"] / aggregate["avg_profit_factor"]))
            aggregate["consistency_score"] = consistency

        return aggregate


class MLSignalEnhancer:
    """Machine learning component to enhance signal quality and reduce false positives."""

    def __init__(self):
        self.model = None
        self.scaler = None
        self.feature_names = []
        self.is_trained = False

    def extract_features(self, df: pd.DataFrame, params: Dict) -> pd.DataFrame:
        """Extract features for ML model."""
        df = df.copy()

        # Basic price features
        df['returns'] = df['Close'].pct_change()
        df['log_returns'] = np.log(df['Close'] / df['Close'].shift(1))
        df['hl_ratio'] = (df['High'] - df['Low']) / df['Close']
        df['oc_ratio'] = (df['Open'] - df['Close']).abs() / df['Close']

        # Volume-like features (using tick volume approximation)
        df['price_range'] = df['High'] - df['Low']
        df['body_size'] = (df['Close'] - df['Open']).abs()
        df['upper_wick'] = df['High'] - np.maximum(df['Open'], df['Close'])
        df['lower_wick'] = np.minimum(df['Open'], df['Close']) - df['Low']

        # Volatility features
        df['volatility_5'] = df['returns'].rolling(5).std()
        df['volatility_20'] = df['returns'].rolling(20).std()

        # Momentum features
        df['rsi_momentum'] = df['rsi'].diff(3)
        df['price_momentum_5'] = df['Close'].pct_change(5)
        df['price_momentum_20'] = df['Close'].pct_change(20)

        # Mean reversion features
        df['distance_from_ma_20'] = (df['Close'] - df['Close'].rolling(20).mean()) / df['Close']
        df['distance_from_ma_50'] = (df['Close'] - df['Close'].rolling(50).mean()) / df['Close']

        # Market microstructure
        df['efficiency_ratio'] = np.abs(df['Close'] - df['Close'].shift(10)) / \
                                df['price_range'].rolling(10).sum().replace(0, np.nan)

        # Time features
        df['hour'] = df.index.hour
        df['day_of_week'] = df.index.dayofweek

        # Lagged features
        for lag in [1, 2, 3, 5]:
            df[f'close_lag_{lag}'] = df['Close'].shift(lag)
            df[f'returns_lag_{lag}'] = df['returns'].shift(lag)
            df[f'rsi_lag_{lag}'] = df['rsi'].shift(lag)

        return df

    def create_labels(self, df: pd.DataFrame, params: Dict, pip_size: float) -> pd.Series:
        """Create labels for supervised learning (future profitability)."""
        # Simple label: whether a trade entered at this bar would be profitable
        # This is a simplified approach - in practice would use more sophisticated labeling

        signals = compute_signals(df, params, pip_size)
        trades = simulate_trades(df, signals, params, pip_size)

        if trades.empty:
            return pd.Series(0, index=df.index)  # No trades = no signal

        # Create profitability label for each bar
        labels = pd.Series(0, index=df.index)

        for _, trade in trades.iterrows():
            entry_idx = trade['entry_idx']
            # Label the entry bar as profitable if the trade made money
            if trade['pnl'] > 0:
                labels.iloc[entry_idx] = 1
            else:
                labels.iloc[entry_idx] = -1  # Losing trade

        return labels

    def train(self, df: pd.DataFrame, symbol: str, params: Dict) -> Dict:
        """Train the ML model to predict signal quality."""
        if not SKLEARN_AVAILABLE:
            return {"error": "scikit-learn not available"}

        try:
            pip_size = get_pip_size(symbol)

            # Extract features
            featured_df = self.extract_features(df, params)
            featured_df = featured_df.dropna()

            if len(featured_df) < 100:
                return {"error": "Insufficient data for ML training"}

            # Create labels
            labels = self.create_labels(featured_df, params, pip_size)

            # Align features and labels
            min_len = min(len(featured_df), len(labels))
            featured_df = featured_df.iloc[:min_len]
            labels = labels.iloc[:min_len]

            # Select feature columns (exclude non-feature columns)
            exclude_cols = ['Open', 'High', 'Low', 'Close', 'Volume']
            feature_cols = [col for col in featured_df.columns if col not in exclude_cols]

            # Handle infinite and NaN values
            X = featured_df[feature_cols].replace([np.inf, -np.inf], np.nan).fillna(0)
            y = (labels > 0).astype(int)  # Binary classification: profitable vs not

            # Store feature names
            self.feature_names = list(X.columns)

            # Scale features
            self.scaler = StandardScaler()
            X_scaled = self.scaler.fit_transform(X)

            # Train model
            self.model = RandomForestClassifier(
                n_estimators=100,
                max_depth=10,
                min_samples_split=20,
                min_samples_leaf=10,
                random_state=42,
                n_jobs=-1
            )
            self.model.fit(X_scaled, y)

            self.is_trained = True

            # Calculate feature importance
            feature_importance = dict(zip(self.feature_names, self.model.feature_importances_))

            return {
                "status": "trained",
                "feature_count": len(self.feature_names),
                "training_samples": len(X),
                "positive_samples": int(y.sum()),
                "negative_samples": int(len(y) - y.sum()),
                "feature_importance": feature_importance
            }

        except Exception as e:
            return {"error": str(e)}

    def predict_signal_quality(self, df: pd.DataFrame, params: Dict, pip_size: float) -> np.ndarray:
        """Predict signal quality score (0-1) for each bar."""
        if not self.is_trained or not SKLEARN_AVAILABLE:
            # Return neutral scores if not trained
            return np.full(len(df), 0.5)

        try:
            # Extract features
            featured_df = self.extract_features(df, params)
            featured_df = featured_df.dropna()

            if len(featured_df) == 0:
                return np.array([])

            # Select same features used in training
            X = featured_df[self.feature_names].replace([np.inf, -np.inf], np.nan).fillna(0)

            # Scale and predict
            X_scaled = self.scaler.transform(X)
            probabilities = self.model.predict_proba(X_scaled)[:, 1]  # Probability of positive class

            return probabilities

        except Exception as e:
            print(f"Error in ML prediction: {e}")
            return np.full(len(df), 0.5)  # Return neutral scores on error


def enhanced_compute_signals(df: pd.DataFrame, p: dict, pip_size: float,
                           session_hours: list = None, ml_enhancer: MLSignalEnhancer = None) -> pd.Series:
    """Enhanced signal computation with ML-based signal filtering."""
    # Get original signals
    original_signals = compute_signals(df, p, pip_size, session_hours=session_hours)

    # If ML enhancer is available and trained, apply filtering
    if ml_enhancer and ml_enhancer.is_trained:
        # Get ML predictions for signal quality
        ml_scores = ml_enhancer.predict_signal_quality(df, p, pip_size)

        # Only take signals where ML confidence is above threshold
        threshold = 0.6  # Require 60% confidence from ML model
        enhanced_signals = original_signals.copy()

        # Zero out signals with low ML confidence
        for i in range(len(enhanced_signals)):
            if enhanced_signals.iloc[i] != 0 and ml_scores[i] < threshold:
                enhanced_signals.iloc[i] = 0

        return enhanced_signals

    return original_signals


def run_enhanced_backtest(symbol: str, months: int, params: dict = None,
                         use_walk_forward: bool = False, use_ml_enhancement: bool = False) -> dict:
    """Run enhanced backtest with optional walk-forward analysis and ML enhancement."""
    if params is None:
        params = DEFAULT_PARAMS.copy()

    if use_walk_forward:
        # Use walk-forward analysis
        wf_analyzer = WalkForwardAnalyzer(training_months=3, testing_months=1)
        return wf_analyzer.analyze(symbol, params, months)

    elif use_ml_enhancement and SKLEARN_AVAILABLE:
        # Use ML-enhanced signal generation
        print(f"Fetching {months} months of data for ML-enhanced backtest...")

        if not connect():
            return {"error": "Failed to connect to MT5"}

        bars = months * 30 * 24 * 60  # Approximate M1 bars
        df = fetch_ohlcv(symbol, mt5.TIMEFRAME_M1, bars)
        disconnect()

        if df.empty:
            return {"error": "No data fetched"}

        print(f"Got {len(df)} bars from {df.index[0]} to {df.index[-1]}")

        # Split data for training/testing (use first 70% for training, last 30% for testing)
        split_idx = int(len(df) * 0.7)
        train_df = df.iloc[:split_idx].copy()
        test_df = df.iloc[split_idx:].copy()

        print(f"Training set: {len(train_df)} bars from {train_df.index[0]} to {train_df.index[-1]}")
        print(f"Testing set:  {len(test_df)} bars from {test_df.index[0]} to {test_df.index[-1]}")

        # Train ML enhancer on training data
        ml_enhancer = MLSignalEnhancer()
        print("Training ML signal enhancer...")
        train_result = ml_enhancer.train(train_df, symbol, params)

        if "error" in train_result:
            print(f"ML training failed: {train_result['error']}")
            print("Falling back to standard backtest...")
            use_ml_enhancement = False
        else:
            print(f"ML training completed: {train_result}")

        # Run backtest on test data with ML enhancement
        if use_ml_enhancement:
            pip_size = get_pip_size(symbol)

            # Add indicators to test data
            test_df_ind = add_indicators(test_df.copy(), params)
            test_df_ind = test_df_ind.dropna()

            if test_df_ind.empty:
                return {"error": "No data after indicators"}

            # Get symbol config
            sym_cfg = SYMBOL_CONFIG.get(symbol, SYMBOL_CONFIG["EURUSD"])
            session_hours = sym_cfg.get("session_hours")

            # Generate enhanced signals
            signals = enhanced_compute_signals(
                test_df_ind, params, pip_size,
                session_hours=session_hours,
                ml_enhancer=ml_enhancer
            )

            # Simulate trades
            trades = simulate_trades(test_df_ind, signals, params, pip_size)

            # Compute metrics
            metrics = compute_metrics(trades, params["InitialBalance"])

            return {
                "analysis_type": "ml_enhanced",
                "symbol": symbol,
                "ml_training_result": train_result,
                "metrics": metrics,
                "trades": trades,
                "test_period": {
                    "start": test_df.index[0].isoformat(),
                    "end": test_df.index[-1].isoformat()
                }
            }

    # Standard backtest (fallback)
    from backtest import run
    return run(symbol, months, params)


def print_enhanced_results(result: dict):
    """Print results from enhanced backtest analysis."""
    if "error" in result:
        print(f"ERROR: {result['error']}")
        return

    analysis_type = result.get("analysis_type", "standard")

    if analysis_type == "walk_forward":
        print("\n" + "=" * 60)
        print(f"  WALK-FORWARD ANALYSIS RESULTS — {result['symbol']}")
        print("=" * 60)
        print(f"Windows analyzed: {result['windows']}")

        agg = result.get("aggregate_metrics", {})
        if agg and "error" not in agg:
            print(f"\nAggregate Performance Metrics:")
            print(f"  Avg Win Rate:     {agg.get('avg_win_rate_pct', 0):.1f}% ± {agg.get('std_win_rate_pct', 0):.1f}%")
            print(f"  Avg Profit Factor: {agg.get('avg_profit_factor', 0):.2f} ± {agg.get('std_profit_factor', 0):.2f}")
            print(f"  Avg Max DD:       {agg.get('avg_max_drawdown_pct', 0):.2f}% ± {agg.get('std_max_drawdown_pct', 0):.2f}%")
            print(f"  Avg Sharpe Ratio:  {agg.get('avg_sharpe_ratio', 0):.2f} ± {agg.get('std_sharpe_ratio', 0):.2f}")

            if "consistency_score" in agg:
                print(f"  Consistency Score: {agg.get('consistency_score', 0):.2f} (1.0 = perfectly consistent)")

        # Show best and worst windows
        windows = result.get("window_results", [])
        if windows:
            # Sort by profit factor
            sorted_windows = sorted(
                [w for w in windows if "test_metrics" in w and "profit_factor" in w["test_metrics"]],
                key=lambda x: x["test_metrics"]["profit_factor"],
                reverse=True
            )

            if sorted_windows:
                best = sorted_windows[0]
                worst = sorted_windows[-1]
                print(f"\nBest Window ({best['window']}): PF {best['test_metrics']['profit_factor']:.2f}, "
                      f"WR {best['test_metrics']['win_rate_pct']:.1f}%")
                print(f"Worst Window ({worst['window']}): PF {worst['test_metrics']['profit_factor']:.2f}, "
                      f"WR {worst['test_metrics']['win_rate_pct']:.1f}%")

    elif analysis_type == "ml_enhanced":
        print("\n" + "=" * 60)
        print(f"  ML-ENHANCED BACKTEST RESULTS — {result['symbol']}")
        print("=" * 60)

        ml_result = result.get("ml_training_result", {})
        if "error" not in ml_result:
            print(f"ML Training: {ml_result.get('positive_samples', 0)} wins, "
                  f"{ml_result.get('negative_samples', 0)} losses")
            print(f"Top 5 Features: {dict(list(ml_result.get('feature_importance', {}).items())[:5])}")

        metrics = result.get("metrics", {})
        if metrics and "error" not in metrics:
            print(f"\nOut-of-Sample Performance:")
            print(f"  Total Trades:    {metrics.get('total_trades', 0)}")
            print(f"  Wins / Losses:   {metrics.get('wins', 0)} / {metrics.get('losses', 0)}")
            print(f"  Win Rate:        {metrics.get('win_rate_pct', 0):.1f}%")
            print(f"  Profit Factor:   {metrics.get('profit_factor', 0):.2f}")
            print(f"  Net P&L:         ${metrics.get('net_pnl', 0):.2f}")
            print(f"  Max Drawdown:    {metrics.get('max_drawdown_pct', 0):.2f}%")
            print(f"  Sharpe Ratio:    {metrics.get('sharpe_ratio', 0):.2f}")
            print(f"  Final Balance:   ${metrics.get('final_balance', 0):.2f}")

    else:
        # Standard backtest results
        from backtest import print_results
        print_results(result)


def main():
    parser = argparse.ArgumentParser(description="Enhanced ScalpMaster HFT Backtest")
    parser.add_argument("--symbol", default="EURUSD", help="Symbol to backtest")
    parser.add_argument("--months", type=int, default=12, help="Months of M1 history")
    parser.add_argument("--walk-forward", action="store_true",
                       help="Use walk-forward analysis (recommended for robust parameter testing)")
    parser.add_argument("--ml-enhance", action="store_true",
                       help="Use ML-enhanced signal filtering (requires scikit-learn)")
    parser.add_argument("--params", type=str, help="JSON string of parameters to override defaults")

    args = parser.parse_args()

    # Parse custom parameters if provided
    params = DEFAULT_PARAMS.copy()
    if args.params:
        try:
            custom_params = json.loads(args.params)
            params.update(custom_params)
            print(f"Using custom parameters: {custom_params}")
        except json.JSONDecodeError:
            print("Error: Invalid JSON in --params parameter")
            sys.exit(1)

    # Run enhanced backtest
    result = run_enhanced_backtest(
        symbol=args.symbol.upper(),
        months=args.months,
        params=params,
        use_walk_forward=args.walk_forward,
        use_ml_enhancement=args.ml_enhance
    )

    print_enhanced_results(result)


if __name__ == "__main__":
    main()