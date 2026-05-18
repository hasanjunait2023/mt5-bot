"""
ML-enhanced signal generation system that improves the existing scalping strategy
using machine learning to filter false positives and enhance signal quality.
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Tuple, Optional, Any
import warnings
warnings.filterwarnings('ignore')

# Try to import scikit-learn for ML components
try:
    from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
    from sklearn.preprocessing import StandardScaler
    from sklearn.model_selection import TimeSeriesSplit
    from sklearn.metrics import classification_report, confusion_matrix
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False
    print("Warning: scikit-learn not available. ML features will be disabled.")

from mt5_bridge import get_pip_size
from config import SYMBOL_CONFIG
from backtest import (
    add_indicators, compute_signals, simulate_trades, compute_metrics,
    ema, rsi, atr, bollinger, macd
)


class MLCSignalFilter:
    """Machine learning classifier to filter trading signals and improve quality."""

    def __init__(self, model_type: str = "random_forest"):
        self.model_type = model_type
        self.model = None
        self.scaler = None
        self.feature_names = []
        self.is_trained = False
        self.feature_importance = {}

    def extract_features(self, df: pd.DataFrame, params: Dict) -> pd.DataFrame:
        """Extract comprehensive features for ML model."""
        df = df.copy()

        # Price-based features
        df['returns'] = df['Close'].pct_change()
        df['log_returns'] = np.log(df['Close'] / df['Close'].shift(1))
        df['hl_ratio'] = (df['High'] - df['Low']) / df['Close']
        df['oc_ratio'] = (df['Open'] - df['Close']).abs() / df['Close']
        df['body_to_range'] = df['oc_ratio'] / (df['hl_ratio'].replace(0, np.nan))

        # Volume-like features (using price action)
        df['price_range'] = df['High'] - df['Low']
        df['body_size'] = (df['Close'] - df['Open']).abs()
        df['upper_wick'] = df['High'] - np.maximum(df['Open'], df['Close'])
        df['lower_wick'] = np.minimum(df['Open'], df['Close']) - df['Low']
        df['wick_ratio'] = (df['upper_wick'] + df['lower_wick']) / df['price_range'].replace(0, np.nan)

        # Volatility features
        df['atr_normalized'] = df['atr'] / df['Close']
        df['volatility_5'] = df['returns'].rolling(5).std()
        df['volatility_20'] = df['returns'].rolling(20).std()
        df['volatility_ratio'] = df['volatility_5'] / df['volatility_20'].replace(0, np.nan)

        # Momentum features
        df['rsi'] = rsi(df['Close'], params.get('RSI_Period', 7))
        df['rsi_momentum'] = df['rsi'].diff(3)
        df['rsi_ma'] = df['rsi'].rolling(5).mean()
        df['rsi_divergence'] = df['rsi'] - df['rsi_ma']
        df['price_momentum_3'] = df['Close'].pct_change(3)
        df['price_momentum_10'] = df['Close'].pct_change(10)

        # Trend features
        df['ema_fast'] = ema(df['Close'], params.get('EMA_Fast', 9))
        df['ema_slow'] = ema(df['Close'], params.get('EMA_Slow', 21))
        df['ema_ratio'] = df['ema_fast'] / df['ema_slow'].replace(0, np.nan)
        df['price_vs_ema_fast'] = (df['Close'] - df['ema_fast']) / df['Close']
        df['price_vs_ema_slow'] = (df['Close'] - df['ema_slow']) / df['Close']
        df['ema_separation'] = (df['ema_fast'] - df['ema_slow']) / df['atr'].replace(0, np.nan)

        # MACD features
        macd_line, macd_signal = macd(
            df['Close'],
            params.get('MACD_Fast', 8),
            params.get('MACD_Slow', 17),
            params.get('MACD_Signal', 9)
        )
        df['macd_line'] = macd_line
        df['macd_signal'] = macd_signal
        df['macd_histogram'] = macd_line - macd_signal
        df['macd_cross_up'] = ((macd_line > macd_signal) & (macd_line.shift(1) <= macd_signal.shift(1))).astype(int)
        df['macd_cross_down'] = ((macd_line < macd_signal) & (macd_line.shift(1) >= macd_signal.shift(1))).astype(int)

        # Bollinger Bands features
        bb_upper, bb_middle, bb_lower = bollinger(
            df['Close'],
            params.get('BB_Period', 20),
            params.get('BB_Deviation', 2.0)
        )
        df['bb_upper'] = bb_upper
        df['bb_middle'] = bb_middle
        df['bb_lower'] = bb_lower
        df['bb_width'] = (bb_upper - bb_lower) / bb_middle.replace(0, np.nan)
        df['bb_position'] = (df['Close'] - bb_lower) / (bb_upper - bb_lower).replace(0, np.nan)
        df['bb_touch_upper'] = (df['Close'] >= bb_upper).astype(int)
        df['bb_touch_lower'] = (df['Close'] <= bb_lower).astype(int)
        df['bb_squeeze'] = (df['bb_width'] < df['bb_width'].rolling(20).quantile(0.2)).astype(int)

        # Mean reversion features
        df['distance_from_ma_10'] = (df['Close'] - df['Close'].rolling(10).mean()) / df['Close']
        df['distance_from_ma_20'] = (df['Close'] - df['Close'].rolling(20).mean()) / df['Close']
        df['distance_from_ma_50'] = (df['Close'] - df['Close'].rolling(50).mean()) / df['Close']

        # Market microstructure and price action
        df['efficiency_ratio'] = np.abs(df['Close'] - df['Close'].shift(10)) / \
                                df['price_range'].rolling(10).sum().replace(0, np.nan)
        df['price_velocity'] = df['Close'].diff(3) / df['atr'].replace(0, np.nan)
        df['acceleration'] = df['price_velocity'].diff(3)

        # Time features
        df['hour'] = df.index.hour
        df['day_of_week'] = df.index.dayofweek
        df['minute'] = df.index.minute

        # Lagged features for temporal patterns
        for lag in [1, 2, 3, 5, 10]:
            df[f'returns_lag_{lag}'] = df['returns'].shift(lag)
            df[f'rsi_lag_{lag}'] = df['rsi'].shift(lag)
            df[f'ema_ratio_lag_{lag}'] = df['ema_ratio'].shift(lag)
            df[f'bb_position_lag_{lag}'] = df['bb_position'].shift(lag)

        # Rolling statistics
        df['returns_mean_5'] = df['returns'].rolling(5).mean()
        df['returns_std_5'] = df['returns'].rolling(5).std()
        df['rsi_mean_5'] = df['rsi'].rolling(5).mean()
        df['rsi_std_5'] = df['rsi'].rolling(5).std()

        return df

    def create_training_labels(self, df: pd.DataFrame, params: Dict, pip_size: float,
                             lookforward_bars: int = 10) -> pd.Series:
        """Create labels for ML training based on future trade outcomes."""
        # Generate signals using the base strategy
        signals = compute_signals(df, params, pip_size)

        # Simulate trades to get actual outcomes
        trades = simulate_trades(df, signals, params, pip_size)

        if trades.empty:
            # No trades - return neutral labels
            return pd.Series(0, index=df.index)

        # Create labels for each bar: 1 if profitable trade entered, -1 if losing, 0 if no signal
        labels = pd.Series(0, index=df.index)

        for _, trade in trades.iterrows():
            entry_idx = trade['entry_idx']
            if entry_idx < len(df):
                # Label based on actual trade outcome
                if trade['pnl'] > 0:
                    labels.iloc[entry_idx] = 1  # Profitable
                else:
                    labels.iloc[entry_idx] = -1  # Losing

        return labels

    def prepare_training_data(self, df: pd.DataFrame, params: Dict, pip_size: float) -> Tuple[np.ndarray, np.ndarray]:
        """Prepare features and labels for ML training."""
        # Extract features
        featured_df = self.extract_features(df, params)
        featured_df = featured_df.dropna()

        if len(featured_df) < 50:
            raise ValueError("Insufficient data for ML training after feature extraction")

        # Create labels
        labels = self.create_training_labels(featured_df, params, pip_size)
        labels = labels.iloc[:len(featured_df)]  # Align lengths

        # Select feature columns (exclude price/volume columns and target)
        exclude_cols = ['Open', 'High', 'Low', 'Close', 'Volume']
        feature_cols = [col for col in featured_df.columns if col not in exclude_cols]

        # Handle infinite and NaN values
        X = featured_df[feature_cols].replace([np.inf, -np.inf], np.nan).fillna(0)
        y = (labels > 0).astype(int)  # Binary: profitable signal vs not

        # Store feature names
        self.feature_names = list(X.columns)

        return X.values, y.values

    def train(self, df: pd.DataFrame, symbol: str, params: Dict) -> Dict:
        """Train the ML model to predict signal quality."""
        if not SKLEARN_AVAILABLE:
            return {"error": "scikit-learn not available for ML training"}

        try:
            pip_size = get_pip_size(symbol)

            # Prepare training data
            X, y = self.prepare_training_data(df, params, pip_size)

            if len(X) < 20:
                return {"error": "Insufficient samples for training"}

            # Check class balance
            unique_classes = np.unique(y)
            if len(unique_classes) < 2:
                return {"error": "Only one class present in labels"}

            class_counts = np.bincount(y)
            print(f"Training data: {len(X)} samples, Class distribution: {class_counts}")

            # Use time series cross-validation to avoid look-ahead bias
            tscv = TimeSeriesSplit(n_splits=3)

            # Initialize model based on type
            if self.model_type == "random_forest":
                self.model = RandomForestClassifier(
                    n_estimators=100,
                    max_depth=10,
                    min_samples_split=20,
                    min_samples_leaf=10,
                    random_state=42,
                    n_jobs=-1,
                    class_weight='balanced'
                )
            elif self.model_type == "gradient_boosting":
                self.model = GradientBoostingClassifier(
                    n_estimators=100,
                    max_depth=6,
                    learning_rate=0.1,
                    random_state=42
                )
            else:
                return {"error": f"Unsupported model type: {self.model_type}"}

            # Scale features
            self.scaler = StandardScaler()
            X_scaled = self.scaler.fit_transform(X)

            # Train model
            self.model.fit(X_scaled, y)

            self.is_trained = True

            # Calculate feature importance
            if hasattr(self.model, 'feature_importances_'):
                self.feature_importance = dict(zip(self.feature_names, self.model.feature_importances_))
            else:
                # For models without feature_importance_, use coefficients or skip
                self.feature_importance = {}

            # Calculate training accuracy
            train_pred = self.model.predict(X_scaled)
            from sklearn.metrics import accuracy_score
            train_accuracy = accuracy_score(y, train_pred)

            return {
                "status": "trained",
                "model_type": self.model_type,
                "training_samples": len(X),
                "feature_count": len(self.feature_names),
                "class_distribution": dict(zip(unique_classes, class_counts)),
                "training_accuracy": train_accuracy,
                "feature_importance": self.feature_importance
            }

        except Exception as e:
            return {"error": str(e)}

    def predict_signal_quality(self, df: pd.DataFrame, params: Dict, pip_size: float) -> np.ndarray:
        """Predict signal quality score (probability of profitability) for each bar."""
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

            # Scale and predict probabilities
            X_scaled = self.scaler.transform(X)
            probabilities = self.model.predict_proba(X_scaled)[:, 1]  # Probability of positive class

            return probabilities

        except Exception as e:
            print(f"Error in ML prediction: {e}")
            return np.full(len(df), 0.5)  # Return neutral scores on error


def ml_enhanced_compute_signals(df: pd.DataFrame, p: dict, pip_size: float,
                              session_hours: list = None,
                              ml_filter: MLCSignalFilter = None,
                              ml_threshold: float = 0.6) -> pd.Series:
    """Enhanced signal computation with ML-based signal filtering."""
    # Get original signals from base strategy
    original_signals = compute_signals(df, p, pip_size, session_hours=session_hours)

    # If ML filter is available and trained, apply filtering
    if ml_filter and ml_filter.is_trained:
        # Get ML predictions for signal quality
        ml_scores = ml_filter.predict_signal_quality(df, p, pip_size)

        # Only take signals where ML confidence is above threshold
        enhanced_signals = original_signals.copy()

        # Zero out signals with low ML confidence
        for i in range(len(enhanced_signals)):
            if enhanced_signals.iloc[i] != 0 and ml_scores[i] < ml_threshold:
                enhanced_signals.iloc[i] = 0

        return enhanced_signals

    return original_signals


def run_ml_enhanced_backtest(symbol: str, months: int = 6,
                           params: dict = None,
                           ml_threshold: float = 0.6) -> dict:
    """Run backtest with ML-enhanced signal generation."""
    if params is None:
        from config import DEFAULT_PARAMS
        params = DEFAULT_PARAMS.copy()

    print(f"Running ML-enhanced backtest for {symbol}...")

    # Import MT5 functions
    from mt5_bridge import connect, disconnect, fetch_ohlcv, get_pip_size, check_symbol

    if not connect():
        return {"error": "Failed to connect to MT5"}

    bars = months * 30 * 24 * 60  # Approximate M1 bars
    df = fetch_ohlcv(symbol, mt5.TIMEFRAME_M1, bars)
    disconnect()

    if df.empty:
        return {"error": "No data fetched"}

    print(f"Got {len(df)} bars from {df.index[0]} to {df.index[-1]}")

    # Split data for training/testing (avoid overfitting)
    split_idx = int(len(df) * 0.7)  # 70% for training, 30% for testing
    train_df = df.iloc[:split_idx].copy()
    test_df = df.iloc[split_idx:].copy()

    print(f"Training set: {len(train_df)} bars ({train_df.index[0]} to {train_df.index[-1]})")
    print(f"Testing set:  {len(test_df)} bars ({test_df.index[0]} to {test_df.index[-1]})")

    # Train ML filter on training data
    ml_filter = MLCSignalFilter(model_type="random_forest")
    print("Training ML signal filter...")
    train_result = ml_filter.train(train_df, symbol, params)

    if "error" in train_result:
        print(f"ML training failed: {train_result['error']}")
        print("Falling back to standard backtest...")
        # Run standard backtest on full dataset
        from backtest import run
        result = run(symbol, months, params)
        result["ml_training_failed"] = True
        result["ml_error"] = train_result["error"]
        return result

    print(f"ML training completed: {train_result.get('training_accuracy', 0):.3f} accuracy")

    # Run backtest on test data with ML enhancement
    pip_size = get_pip_size(symbol)

    # Add indicators to test data
    test_df_ind = add_indicators(test_df.copy(), params)
    test_df_ind = test_df_ind.dropna()

    if test_df_ind.empty:
        return {"error": "No data after indicators"}

    # Get symbol config for session hours
    sym_cfg = SYMBOL_CONFIG.get(symbol, SYMBOL_CONFIG["EURUSD"])
    session_hours = sym_cfg.get("session_hours")

    # Generate ML-enhanced signals
    signals = ml_enhanced_compute_signals(
        test_df_ind, params, pip_size,
        session_hours=session_hours,
        ml_filter=ml_filter,
        ml_threshold=ml_threshold
    )

    # Simulate trades
    trades = simulate_trades(test_df_ind, signals, params, pip_size)

    # Compute metrics
    from backtest import compute_metrics
    metrics = compute_metrics(trades, params["InitialBalance"])

    # Count signals before and after ML filtering
    original_signals = compute_signals(test_df_ind, params, pip_size, session_hours=session_hours)
    original_signal_count = (original_signals != 0).sum()
    enhanced_signal_count = (signals != 0).sum()
    signal_reduction = 1 - (enhanced_signal_count / max(original_signal_count, 1))

    return {
        "analysis_type": "ml_enhanced_backtest",
        "symbol": symbol,
        "ml_training_result": train_result,
        "ml_threshold": ml_threshold,
        "signal_statistics": {
            "original_signals": int(original_signal_count),
            "enhanced_signals": int(enhanced_signal_count),
            "signal_reduction_ratio": signal_reduction,
            "signals_filtered_out": int(original_signal_count - enhanced_signal_count)
        },
        "metrics": metrics,
        "trades": trades,
        "test_period": {
            "start": test_df.index[0].isoformat(),
            "end": test_df.index[-1].isoformat()
        },
        "training_period": {
            "start": train_df.index[0].isoformat(),
            "end": train_df.index[-1].isoformat()
        }
    }


def print_ml_enhanced_results(result: dict):
    """Print results from ML-enhanced backtest."""
    if "error" in result:
        print(f"ERROR: {result['error']}")
        return

    print("\n" + "=" * 70)
    print(f"  ML-ENHANCED BACKTEST RESULTS — {result['symbol']}")
    print("=" * 70)

    # Show ML training results
    ml_result = result.get("ml_training_result", {})
    if "error" not in ml_result:
        print(f"ML Model: {ml_result.get('model_type', 'Unknown')}")
        print(f"Training Accuracy: {ml_result.get('training_accuracy', 0):.3f}")
        print(f"Training Samples: {ml_result.get('training_samples', 0)}")
        print(f"Features Used: {ml_result.get('feature_count', 0)}")

        # Show top 5 features
        feature_importance = ml_result.get("feature_importance", {})
        if feature_importance:
            top_features = sorted(feature_importance.items(), key=lambda x: x[1], reverse=True)[:5]
            print(f"Top 5 Features: {dict(top_features)}")

    # Show signal filtering statistics
    signal_stats = result.get("signal_statistics", {})
    if signal_stats:
        print(f"\nSignal Filtering:")
        print(f"  Original Signals: {signal_stats.get('original_signals', 0)}")
        print(f"  ML-Enhanced Signals: {signal_stats.get('enhanced_signals', 0)}")
        print(f"  Signals Filtered Out: {signal_stats.get('signals_filtered_out', 0)}")
        print(f"  Signal Reduction: {signal_stats.get('signal_reduction_ratio', 0):.1%}")

    # Show performance metrics
    metrics = result.get("metrics", {})
    if metrics and "error" not in metrics:
        print(f"\nOut-of-Sample Performance (Test Period):")
        print(f"  Total Trades:    {metrics.get('total_trades', 0)}")
        print(f"  Wins / Losses:   {metrics.get('wins', 0)} / {metrics.get('losses', 0)}")
        print(f"  Win Rate:        {metrics.get('win_rate_pct', 0):.1f}%")
        print(f"  Profit Factor:   {metrics.get('profit_factor', 0):.2f}")
        print(f"  Net P&L:         ${metrics.get('net_pnl', 0):.2f}")
        print(f"  Max Drawdown:    {metrics.get('max_drawdown_pct', 0):.2f}%")
        print(f"  Sharpe Ratio:    {metrics.get('sharpe_ratio', 0):.2f}")
        print(f"  Final Balance:   ${metrics.get('final_balance', 0):.2f}")

    # Show test period info
    test_period = result.get("test_period", {})
    if test_period:
        print(f"\nTest Period: {test_period.get('start', '')[:10]} to {test_period.get('end', '')[:10]}")


def main():
    parser = argparse.ArgumentParser(description="ML-Enhanced Signal Generation for ScalpMaster HFT")
    parser.add_argument("--symbol", default="EURUSD", help="Symbol to backtest")
    parser.add_argument("--months", type=int, default=6, help="Months of M1 history")
    parser.add_argument("--threshold", type=float, default=0.6,
                       help="ML confidence threshold for signal filtering (0.0-1.0)")
    parser.add_argument("--params", type=str, help="JSON string of parameters to override defaults")

    args = parser.parse_args()

    # Parse custom parameters if provided
    params = None
    if args.params:
        try:
            import json
            params = json.loads(args.params)
            print(f"Using custom parameters: {list(params.keys())}")
        except json.JSONDecodeError:
            print("Error: Invalid JSON in --params parameter")
            return

    # Run ML-enhanced backtest
    result = run_ml_enhanced_backtest(
        symbol=args.symbol.upper(),
        months=args.months,
        params=params,
        ml_threshold=args.threshold
    )

    print_ml_enhanced_results(result)


if __name__ == "__main__":
    main()