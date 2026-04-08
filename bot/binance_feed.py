"""
Binance lead-lag signal feed.

Streams:
  btcusdt@kline_1m    — 1-min candles for momentum (1m / 3m return)
  btcusdt@depth20@100ms — top-20 orderbook for real-time OFI

OFI (Order Flow Imbalance): (bid_vol - ask_vol) / (bid_vol + ask_vol)
  +1 = full bid pressure (bullish), -1 = full ask pressure (bearish)

Signal usage: Polymarket lags Binance by ~30-90s. Strong Binance OFI
signals that the Polymarket token price will adjust shortly after.
"""

import asyncio
import json
from collections import deque
from dataclasses import dataclass, field

import websockets

# Combined stream: klines + depth, one connection
BINANCE_WS_URL = (
    "wss://stream.binance.com:9443/stream"
    "?streams=btcusdt@kline_1m/btcusdt@depth20@100ms"
)

OBI_DEPTH = 5   # Top-N levels for OFI computation


@dataclass
class Candle:
    open_time: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    is_closed: bool


class BinanceFeed:
    """
    Async Binance feed: 1-min klines + real-time orderbook OFI for BTC/USDT.

    get_signal() returns:
      signal      — int: +1 bullish / -1 bearish / 0 neutral (from momentum)
      momentum_1m — float: last closed candle return
      momentum_3m — float: 3-candle return
      ofi         — float: live order book imbalance [-1, +1]
      last_price  — float: latest tick price
    """

    def __init__(self, log_fn=None, on_closed_candle=None):
        self._candles: deque[Candle] = deque(maxlen=5)
        self._ws = None
        self._connected = False
        self._recv_task: asyncio.Task | None = None
        self._log = log_fn or (lambda msg: print("[Binance] %s" % msg))
        # Optional callback: called with a dict when a 1m candle closes
        self._on_closed_candle = on_closed_candle

        # Momentum (updated on closed candles)
        self.momentum_1m: float = 0.0
        self.momentum_3m: float = 0.0
        self.signal: int = 0
        self.last_price: float = 0.0

        # OFI (updated on each depth snapshot, ~100ms)
        self.ofi: float = 0.0           # [-1, +1]
        self._bids: list = []           # [[price, qty], ...]
        self._asks: list = []

    @property
    def connected(self) -> bool:
        return self._connected and self._ws is not None

    async def connect(self):
        try:
            self._ws = await websockets.connect(
                BINANCE_WS_URL,
                ping_interval=30,
                close_timeout=5,
            )
            self._connected = True
            self._recv_task = asyncio.create_task(self._receive_loop())
            self._log("[BinanceFeed] Connected (klines + depth OFI)")
        except Exception as e:
            self._log("[BinanceFeed] Connection failed: %s" % e)
            self._connected = False

    async def disconnect(self):
        self._connected = False
        if self._recv_task:
            self._recv_task.cancel()
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
        self._ws = None

    def get_signal(self, threshold: float | None = None) -> dict:
        """Return current Binance signal dict."""
        return {
            "signal": self.signal,
            "momentum_1m": round(self.momentum_1m, 5),
            "momentum_3m": round(self.momentum_3m, 5),
            "ofi": round(self.ofi, 3),
            "last_price": self.last_price,
            "candles": len(self._candles),
        }

    # ─── Internal ────────────────────────────────────────────────────────

    async def _receive_loop(self):
        try:
            while self._connected and self._ws:
                try:
                    raw = await asyncio.wait_for(self._ws.recv(), timeout=90)
                except asyncio.TimeoutError:
                    self._log("[BinanceFeed] Receive timeout, reconnecting...")
                    self._connected = False
                    break
                except websockets.exceptions.ConnectionClosed:
                    self._log("[BinanceFeed] Connection closed by server")
                    self._connected = False
                    break

                try:
                    msg = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    continue

                # Combined stream wraps data in {"stream": "...", "data": {...}}
                data = msg.get("data", msg)
                stream = msg.get("stream", "")

                if "kline" in stream or "k" in data:
                    self._handle_kline(data)
                elif "depth" in stream or "bids" in data:
                    self._handle_depth(data)

        except asyncio.CancelledError:
            pass
        except Exception as e:
            self._log("[BinanceFeed] Receive loop error: %s" % e)
            self._connected = False

    def _handle_kline(self, data: dict):
        kline = data.get("k")
        if not kline:
            return
        candle = Candle(
            open_time=kline.get("t", 0),
            open=float(kline.get("o", 0) or 0),
            high=float(kline.get("h", 0) or 0),
            low=float(kline.get("l", 0) or 0),
            close=float(kline.get("c", 0) or 0),
            volume=float(kline.get("v", 0) or 0),
            is_closed=kline.get("x", False),
        )
        self.last_price = candle.close
        if candle.is_closed:
            self._candles.append(candle)
            self._update_momentum()
            if self._on_closed_candle is not None:
                from datetime import datetime, timezone
                ts = datetime.fromtimestamp(candle.open_time / 1000, tz=timezone.utc)
                self._on_closed_candle({
                    'ts': ts,
                    'open': candle.open,
                    'high': candle.high,
                    'low': candle.low,
                    'close': candle.close,
                    'volume': candle.volume,
                })

    def _handle_depth(self, data: dict):
        """Update OFI from depth snapshot."""
        bids = data.get("bids", [])
        asks = data.get("asks", [])
        if not bids and not asks:
            return

        self._bids = bids
        self._asks = asks
        self._update_ofi()

    def _update_ofi(self):
        """OFI = (bid_vol_topN - ask_vol_topN) / (bid_vol_topN + ask_vol_topN)."""
        try:
            bid_vol = sum(float(b[1]) for b in self._bids[:OBI_DEPTH])
            ask_vol = sum(float(a[1]) for a in self._asks[:OBI_DEPTH])
            total = bid_vol + ask_vol
            self.ofi = (bid_vol - ask_vol) / total if total > 0 else 0.0
        except Exception:
            self.ofi = 0.0

    def _update_momentum(self, threshold: float = 0.002):
        closed = list(self._candles)
        if len(closed) >= 2 and closed[-2].close > 0:
            self.momentum_1m = (closed[-1].close - closed[-2].close) / closed[-2].close
        else:
            self.momentum_1m = 0.0

        if len(closed) >= 4 and closed[-4].close > 0:
            self.momentum_3m = (closed[-1].close - closed[-4].close) / closed[-4].close
        else:
            self.momentum_3m = self.momentum_1m

        if self.momentum_3m > threshold:
            self.signal = 1
        elif self.momentum_3m < -threshold:
            self.signal = -1
        else:
            self.signal = 0
