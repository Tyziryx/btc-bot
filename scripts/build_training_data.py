"""Build training dataset: features + labels aligned at 5min boundaries."""
import sys
sys.path.insert(0, ".")

import pandas as pd
from bot.config import Config
from bot.data_pipeline import BinanceDataDownloader
from bot.features import FeatureEngine

cfg = Config()
dl = BinanceDataDownloader(data_dir=cfg.DATA_DIR, config=cfg)
engine = FeatureEngine()

print("=== Loading 1min data ===")
df_1min = pd.read_parquet(f"{cfg.DATA_DIR}/BTCUSDT-1m-combined.parquet")
print(f"Loaded {len(df_1min)} candles")

print("=== Loading funding rates ===")
try:
    df_funding = pd.read_parquet(f"{cfg.DATA_DIR}/BTCUSDT-funding-rates.parquet")
    print(f"Loaded {len(df_funding)} funding rate entries")
except FileNotFoundError:
    df_funding = None
    print("No funding data found, using 0")

print("=== Computing features ===")
features = engine.compute_all(df_1min, df_funding)
print(f"Feature matrix: {features.shape}")

print("=== Building 5min labels ===")
df_5min = dl.resample_to_5min(df_1min)
print(f"5min windows: {len(df_5min)}, UP ratio: {df_5min['label'].mean():.4f}")

print("=== Aligning features to labels ===")
# Take features at minute 3 (second-to-last minute of each 5min window)
# This simulates predicting at T-60s to T-30s before window close
# Using minute 4 would leak the label since window_delta at minute 4
# contains almost the entire 5min price change
feat_at_boundary = features[features.index.minute % 5 == 3].copy()
feat_at_boundary.index = feat_at_boundary.index.floor("5min")

common = df_5min.index.intersection(feat_at_boundary.index)
X = feat_at_boundary.loc[common]
y = df_5min.loc[common, "label"]

print(f"Training samples: {len(X)}")
print(f"Features: {list(X.columns)}")
print(f"Label distribution: UP={y.mean():.4f}, DOWN={1-y.mean():.4f}")

X.to_parquet(f"{cfg.DATA_DIR}/training_features.parquet")
y.to_frame("label").to_parquet(f"{cfg.DATA_DIR}/training_labels.parquet")
print(f"\nSaved to {cfg.DATA_DIR}/training_features.parquet")
print(f"Saved to {cfg.DATA_DIR}/training_labels.parquet")
print("Done!")
