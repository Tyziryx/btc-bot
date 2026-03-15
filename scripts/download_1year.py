#!/usr/bin/env python3
"""Download 12 months of BTCUSDT 1-min klines + funding rates."""

import sys
sys.path.insert(0, ".")

from bot.data_pipeline import BinanceDataDownloader

print("=" * 60)
print("  DOWNLOADING 12 MONTHS OF BTCUSDT DATA")
print("=" * 60)

dl = BinanceDataDownloader(data_dir="data")

# Download 12 months of 1min klines
print("\n[1/2] Downloading 1-min klines (12 months)...")
df = dl.download_klines("BTCUSDT", "1m", months=12)

combined_path = "data/BTCUSDT-1m-combined.parquet"
df.to_parquet(combined_path)
print("Saved %d candles to %s" % (len(df), combined_path))
print("Date range: %s to %s" % (df.index.min(), df.index.max()))

# Download funding rates
print("\n[2/2] Downloading funding rates (12 months)...")
df_funding = dl.download_funding_rates("BTCUSDT", months=12)
funding_path = "data/BTCUSDT-funding-rates.parquet"
df_funding.to_parquet(funding_path)
print("Saved %d funding rates" % len(df_funding))

print("\nDONE!")
