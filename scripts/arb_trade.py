#!/usr/bin/env python3
"""
Arb trading script — legging arbitrage on Polymarket BTC 15-min markets.

Usage:
    python scripts/arb_trade.py
    python scripts/arb_trade.py --duration 60
"""

import argparse
import asyncio
import signal
import sys

sys.path.insert(0, ".")

from bot.arb_config import ArbConfig
from bot.arb_trader import ArbTrader


def main():
    parser = argparse.ArgumentParser(description="Legging arbitrage on Polymarket BTC 15min")
    parser.add_argument(
        "--duration", type=int, default=0,
        help="Duration in minutes (0 = run until Ctrl+C)"
    )
    parser.add_argument(
        "--capital", type=float, default=100.0,
        help="Starting paper capital (default: $100)"
    )
    args = parser.parse_args()

    config = ArbConfig()
    trader = ArbTrader(config, capital=args.capital)

    def signal_handler(sig, frame):
        print("\n\nStopping arb trader...")
        trader.print_stats()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)

    print("=" * 58)
    print("  ARB TRADER — Polymarket BTC 15min Legging")
    print("  Paper trading mode — NO REAL ORDERS")
    print("=" * 58)
    print()

    asyncio.run(trader.run(duration_minutes=args.duration))


if __name__ == "__main__":
    main()
