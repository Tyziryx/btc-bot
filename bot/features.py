import numpy as np
import pandas as pd
import ta


class FeatureEngine:
    FEATURE_NAMES = [
        "window_delta", "micro_momentum", "acceleration",
        "cvd", "bid_ask_imbalance", "vwap_deviation",
        "ema_cross", "rsi_14", "z_score",
        "bollinger_bw", "realized_vol_15m", "volume_ratio",
        "candle_body_ratio", "funding_rate",
        "minute_in_window", "hour_sin", "hour_cos",
    ]
    WARMUP_PERIODS = 25

    def compute_all(
        self,
        df_1min: pd.DataFrame,
        df_funding: pd.DataFrame | None = None,
        bid_qty: float = 0.0,
        ask_qty: float = 0.0,
    ) -> pd.DataFrame:
        df = df_1min.copy()
        close = df["close"]
        open_ = df["open"]
        high = df["high"]
        low = df["low"]
        volume = df["volume"]

        features = pd.DataFrame(index=df.index)

        # Cat 1: Direction in window
        window_open = open_.groupby(df.index.floor("5min")).transform("first")
        features["window_delta"] = (close - window_open) / window_open

        returns = close.pct_change()
        features["micro_momentum"] = returns.rolling(2).sum()

        momentum = returns.rolling(2).sum()
        features["acceleration"] = momentum.diff()

        # Cat 2: Order Flow
        if "taker_buy_volume" in df.columns:
            sell_volume = volume - df["taker_buy_volume"]
            buy_volume = df["taker_buy_volume"]
            delta = buy_volume - sell_volume
            features["cvd"] = delta.rolling(5).sum()
        else:
            features["cvd"] = 0.0

        total_qty = bid_qty + ask_qty
        if total_qty > 0:
            features["bid_ask_imbalance"] = (bid_qty - ask_qty) / total_qty
        else:
            features["bid_ask_imbalance"] = 0.0

        cum_vol = volume.rolling(5).sum()
        cum_vwap = (close * volume).rolling(5).sum() / cum_vol
        features["vwap_deviation"] = (close - cum_vwap) / cum_vwap

        # Cat 3: Trend & Momentum
        ema9 = close.ewm(span=9, adjust=False).mean()
        ema21 = close.ewm(span=21, adjust=False).mean()
        features["ema_cross"] = (ema9 - ema21) / ema21

        features["rsi_14"] = ta.momentum.rsi(close, window=14) / 100.0

        sma20 = close.rolling(20).mean()
        std20 = close.rolling(20).std()
        features["z_score"] = (close - sma20) / std20

        # Cat 4: Volatility & Regime
        bb = ta.volatility.BollingerBands(close, window=20, window_dev=2)
        bb_upper = bb.bollinger_hband()
        bb_lower = bb.bollinger_lband()
        bb_middle = bb.bollinger_mavg()
        features["bollinger_bw"] = (bb_upper - bb_lower) / bb_middle

        features["realized_vol_15m"] = returns.rolling(15).std()

        vol_ma3 = volume.rolling(3).mean()
        features["volume_ratio"] = volume / vol_ma3

        # Cat 5: Microstructure & Context
        body = (close - open_).abs()
        wick = high - low + 1e-10
        features["candle_body_ratio"] = body / wick

        if df_funding is not None and not df_funding.empty:
            features["funding_rate"] = (
                df_funding["funding_rate"]
                .reindex(df.index, method="ffill")
                .fillna(0.0)
            )
        else:
            features["funding_rate"] = 0.0

        features["minute_in_window"] = df.index.minute % 5

        hour = df.index.hour + df.index.minute / 60.0
        features["hour_sin"] = np.sin(2 * np.pi * hour / 24)
        features["hour_cos"] = np.cos(2 * np.pi * hour / 24)

        features = features.iloc[self.WARMUP_PERIODS:]
        features = features.dropna()

        return features

    def compute_live(
        self,
        df_1min: pd.DataFrame,
        df_funding: pd.DataFrame | None = None,
        bid_qty: float = 0.0,
        ask_qty: float = 0.0,
    ) -> pd.Series:
        features = self.compute_all(df_1min, df_funding, bid_qty, ask_qty)
        if features.empty:
            raise ValueError("Not enough data to compute features")
        return features.iloc[-1]
