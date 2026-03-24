"""
Binance lead-lag signal feed.

Subscribes to BTC/USDT 1-minute klines via Binance WebSocket.
Computes short-term momentum to use as a directional bias for the
Polymarket arb strategy (Polymarket prices lag Binance by ~30-90s).

Signal: +1 (bullish, UP tokens should rise), -1 (bearish), 0 (neutral).
"""

import asyncio
import json
from collections import deque
from dataclasses import dataclass

import websockets

BINANCE_WS_URL = "wss://stream.binance.com:9443/ws/btcusdt@kline_1m"


@dataclass
class Candle:
    open_time: int
    open: float
    close: float
    is_closed: bool


class BinanceFeed:
    """
    Async Binance 1-minute kline feed for BTC/USDT.

    Usage:
        feed = BinanceFeed(log_fn=my_log)
        await feed.connect()
        ...
        info = feed.get_signal(threshold=0.002)
        # {"signal": 1, "momentum_1m": 0.003, "momentum_3m": 0.005, "last_price": 95000.0}
    """

    def __init__(self, log_fn=None):
        # Keep last 5 closed candles
        self._candles: deque[Candle] = deque(maxlen=5)
        self._ws = None
        self._connected = False
        self._recv_task: asyncio.Task | None = None
        self._log = log_fn or (lambda msg: print("[Binance] %s" % msg))

        # Computed metrics (updated on each closed candle)
        self.momentum_1m: float = 0.0    # Return of last closed candle
        self.momentum_3m: float = 0.0    # Return over last 3 closed candles
        self.signal: int = 0             # -1 / 0 / +1
        self.last_price: float = 0.0     # Latest tick price (live, not necessarily closed)

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
            self._log("[BinanceFeed] Connected to %s" % BINANCE_WS_URL)
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
        """Return current Binance momentum signal dict."""
        return {
            "signal": self.signal,
            "momentum_1m": round(self.momentum_1m, 5),
            "momentum_3m": round(self.momentum_3m, 5),
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
                    # No message in 90s — connection stale
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

                kline = msg.get("k")
                if not kline:
                    continue

                candle = Candle(
                    open_time=kline.get("t", 0),
                    open=float(kline.get("o", 0) or 0),
                    close=float(kline.get("c", 0) or 0),
                    is_closed=kline.get("x", False),
                )
                self.last_price = candle.close

                if candle.is_closed:
                    self._candles.append(candle)
                    self._update_momentum()

        except asyncio.CancelledError:
            pass
        except Exception as e:
            self._log("[BinanceFeed] Receive loop error: %s" % e)
            self._connected = False

    def _update_momentum(self, threshold: float = 0.002):
        """Recompute momentum metrics after a new closed candle arrives."""
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
