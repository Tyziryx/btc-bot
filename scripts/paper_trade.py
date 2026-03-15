#!/usr/bin/env python3
"""
Paper trading script - runs the ML model live against Binance data
without placing real orders.

Usage:
    # Live mode (connects to Binance WebSocket)
    python scripts/paper_trade.py

    # Live mode with time limit (e.g., 60 minutes)
    python scripts/paper_trade.py --duration 60

    # Historical replay mode (fast validation on downloaded data)
    python scripts/paper_trade.py --replay
"""

import argparse
import asyncio
import signal
import sys

sys.path.insert(0, ".")

from bot.config import Config
from bot.paper_trader import PaperTrader


def main():
    parser = argparse.ArgumentParser(description="Paper trading for BTC 5min prediction")
    parser.add_argument(
        "--duration", type=int, default=0,
        help="Duration in minutes (0 = run until Ctrl+C)"
    )
    parser.add_argument(
        "--replay", action="store_true",
        help="Replay on historical data instead of live WebSocket"
    )
    parser.add_argument(
        "--capital", type=float, default=100.0,
        help="Starting paper capital (default: $100)"
    )
    args = parser.parse_args()

    config = Config()
    trader = PaperTrader(config, capital=args.capital)

    # Handle Ctrl+C gracefully
    def signal_handler(sig, frame):
        print("\n\nStopping paper trader...")
        trader.print_stats()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)

    if args.replay:
        # Historical replay mode
        import pandas as pd

        print("Loading historical data for replay...")
        df_1min = pd.read_parquet("data/BTCUSDT-1m-combined.parquet")
        df_labels = pd.read_parquet("data/training_labels.parquet")

        # Use only the last 15% (out-of-sample) for fair test
        n = len(df_labels)
        test_start = int(n * 0.85)
        df_labels_test = df_labels.iloc[test_start:]

        print("Replay period: %s to %s" % (df_labels_test.index.min(), df_labels_test.index.max()))
        print("Windows to replay: %d\n" % len(df_labels_test))

        asyncio.run(trader.run_from_history(df_1min, df_labels_test))
    else:
        # Live WebSocket mode
        print("=" * 60)
        print("  LIVE PAPER TRADING MODE")
        print("  Connecting to Binance WebSocket...")
        print("  Model predictions at minute 3 of each 5-min window")
        print("  Results checked at window close (minute 5)")
        print("  NO REAL ORDERS - simulation only")
        print("=" * 60)
        print()

        asyncio.run(trader.run(duration_minutes=args.duration))


if __name__ == "__main__":
    main()
