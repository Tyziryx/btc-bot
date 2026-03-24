#!/usr/bin/env python3
"""
Arb trading script — legging arbitrage on Polymarket BTC 15-min markets.

Usage:
    python scripts/arb_trade.py
    python scripts/arb_trade.py --duration 60
    python scripts/arb_trade.py --capital 200
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
        help="Duration in minutes (0 = run until Ctrl+C / SIGTERM)"
    )
    parser.add_argument(
        "--capital", type=float, default=100.0,
        help="Starting paper capital (default: $100)"
    )
    args = parser.parse_args()

    config = ArbConfig()
    trader = ArbTrader(config, capital=args.capital)

    print("=" * 60)
    print("  ARB TRADER PRO — Polymarket BTC 15min Legging")
    print("  Paper trading mode — NO REAL ORDERS")
    print("=" * 60)
    print()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    def _request_shutdown():
        """Signal handler: set shutdown flag on the trader (async-safe)."""
        print("\n\nShutdown requested — finishing gracefully...")
        trader._shutdown = True

    # Use loop.add_signal_handler for clean async shutdown (Unix only)
    try:
        loop.add_signal_handler(signal.SIGINT, _request_shutdown)
        loop.add_signal_handler(signal.SIGTERM, _request_shutdown)
    except NotImplementedError:
        # Windows fallback (no asyncio signal support)
        signal.signal(signal.SIGINT, lambda s, f: _request_shutdown())

    try:
        loop.run_until_complete(trader.run(duration_minutes=args.duration))
    finally:
        loop.close()


if __name__ == "__main__":
    main()
