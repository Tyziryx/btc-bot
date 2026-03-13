"""Download 3 months of BTC/USDT 1min klines + funding rates from Binance."""
import sys
sys.path.insert(0, ".")

from bot.config import Config
from bot.data_pipeline import BinanceDataDownloader

cfg = Config()
cfg.ensure_dirs()
dl = BinanceDataDownloader(data_dir=cfg.DATA_DIR, config=cfg)

print("=== Downloading 1min klines ===")
df_1min = dl.download_klines("BTCUSDT", "1m", months=3)
print(f"Total 1min candles: {len(df_1min)}")
print(f"Date range: {df_1min.index[0]} to {df_1min.index[-1]}")

combined_path = f"{cfg.DATA_DIR}/BTCUSDT-1m-combined.parquet"
df_1min.to_parquet(combined_path)
print(f"Saved combined to {combined_path}")

print("\n=== Resampling to 5min ===")
df_5min = dl.resample_to_5min(df_1min)
print(f"Total 5min windows: {len(df_5min)}")
print(f"UP ratio: {df_5min['label'].mean():.4f}")
df_5min.to_parquet(f"{cfg.DATA_DIR}/BTCUSDT-5min-labeled.parquet")

print("\n=== Downloading funding rates ===")
df_funding = dl.download_funding_rates("BTCUSDT", months=3)
print(f"Total funding rates: {len(df_funding)}")
df_funding.to_parquet(f"{cfg.DATA_DIR}/BTCUSDT-funding-rates.parquet")

print("\nDone!")
