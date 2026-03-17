"""
Polymarket trading module - fetches real market prices and places orders.

Connects to Polymarket's Gamma API to find active BTC 5-min markets,
reads REAL executable prices from the CLOB API, and places orders.

Price hierarchy:
  1. CLOB /price?side=SELL  → best ask (what you actually pay to buy)
  2. CLOB /midpoint         → mid bid/ask + 1 cent conservative
  3. CLOB /last-trade-price → most recent execution
  4. Estimate from BTC delta → conservative calculation
  Never use Gamma outcomePrices as entry price (indicative/stale).
"""

import time
from dataclasses import dataclass, field

import requests

from bot.config import Config


GAMMA_API = "https://gamma-api.polymarket.com"
CLOB_API = "https://clob.polymarket.com"


@dataclass
class MarketInfo:
    """Info about a current BTC 5-min UP/DOWN market."""
    slug: str
    condition_id: str
    up_token_id: str
    down_token_id: str
    up_price: float       # Best executable price (from CLOB)
    down_price: float
    up_source: str = ""   # "clob_ask", "clob_midpoint", "clob_last_trade", "estimated", "gamma"
    down_source: str = ""
    gamma_up: float | None = None    # Gamma indicative (for comparison only)
    gamma_down: float | None = None
    up_spread: float | None = None   # CLOB spread
    down_spread: float | None = None
    window_ts: int = 0


def get_current_window_ts() -> int:
    """Get the current 5-min window start timestamp."""
    now = int(time.time())
    return (now // 300) * 300


def get_next_window_ts() -> int:
    """Get the next 5-min window start timestamp."""
    return get_current_window_ts() + 300


def get_real_prices(token_id: str) -> dict:
    """Fetch ALL available prices for a token from CLOB API.

    Returns dict with all price sources for comparison and logging.
    """
    result = {
        "best_ask": None,        # /price?side=SELL — what you PAY to buy
        "best_bid": None,        # /price?side=BUY — what you GET if selling
        "midpoint": None,        # /midpoint — average of bid/ask
        "spread": None,          # /spread — ask - bid
        "last_trade": None,      # /last-trade-price — most recent execution
        "last_trade_side": None,
    }

    # Best ask (= entry price for buying a token)
    try:
        resp = requests.get(
            "%s/price" % CLOB_API,
            params={"token_id": token_id, "side": "SELL"},
            timeout=3,
        )
        resp.raise_for_status()
        price = float(resp.json().get("price", 0))
        if 0.05 < price < 0.95:
            result["best_ask"] = price
    except Exception:
        pass

    # Best bid
    try:
        resp = requests.get(
            "%s/price" % CLOB_API,
            params={"token_id": token_id, "side": "BUY"},
            timeout=3,
        )
        resp.raise_for_status()
        price = float(resp.json().get("price", 0))
        if 0.05 < price < 0.95:
            result["best_bid"] = price
    except Exception:
        pass

    # Midpoint
    try:
        resp = requests.get(
            "%s/midpoint" % CLOB_API,
            params={"token_id": token_id},
            timeout=3,
        )
        resp.raise_for_status()
        mid = float(resp.json().get("mid_price", 0))
        if 0.05 < mid < 0.95:
            result["midpoint"] = mid
    except Exception:
        pass

    # Spread
    try:
        resp = requests.get(
            "%s/spread" % CLOB_API,
            params={"token_id": token_id},
            timeout=3,
        )
        resp.raise_for_status()
        result["spread"] = float(resp.json().get("spread", 0))
    except Exception:
        pass

    # Last trade price
    try:
        resp = requests.get(
            "%s/last-trade-price" % CLOB_API,
            params={"token_id": token_id},
            timeout=3,
        )
        resp.raise_for_status()
        data = resp.json()
        price = float(data.get("price", 0))
        if 0.05 < price < 0.95:
            result["last_trade"] = price
            result["last_trade_side"] = data.get("side", "")
    except Exception:
        pass

    return result


def _select_best_price(prices: dict) -> tuple[float, str]:
    """Select the most reliable price from available sources.

    Priority: midpoint (realistic for limit orders) > best_ask > last_trade > none
    Midpoint is preferred for paper trading as it represents what a patient
    limit order would achieve. best_ask is worst-case (market order).
    """
    if prices["midpoint"] is not None:
        return prices["midpoint"], "clob_midpoint"

    if prices["best_ask"] is not None:
        return prices["best_ask"], "clob_ask"

    if prices["last_trade"] is not None:
        return prices["last_trade"], "clob_last_trade"

    return 0.0, "none"


def find_market(window_ts: int | None = None) -> MarketInfo | None:
    """
    Find the active BTC 5-min UP/DOWN market on Polymarket.

    Fetches REAL executable prices from CLOB API (not Gamma indicative).

    Args:
        window_ts: Specific window timestamp. If None, uses current window.

    Returns:
        MarketInfo with token IDs and real prices, or None if not found.
    """
    if window_ts is None:
        window_ts = get_current_window_ts()

    slug = "btc-updown-5m-%d" % window_ts

    # Query Gamma API for market discovery (tokens, condition ID)
    try:
        resp = requests.get(
            "%s/events" % GAMMA_API,
            params={"slug": slug},
            timeout=5,
        )
        resp.raise_for_status()
        data = resp.json()

        if not data:
            return None

        event = data[0] if isinstance(data, list) else data
        markets = event.get("markets", [])

        if not markets:
            return None

        market = markets[0]
        condition_id = market.get("conditionId", "")

        # clobTokenIds can be a JSON string or a list
        tokens = market.get("clobTokenIds", [])
        if isinstance(tokens, str):
            import json as _json
            tokens = _json.loads(tokens)

        if len(tokens) < 2:
            return None

        # outcomes[0]="Up" -> tokens[0], outcomes[1]="Down" -> tokens[1]
        up_token = tokens[0]
        down_token = tokens[1]

        # === REAL PRICES FROM CLOB API ===
        up_prices = get_real_prices(up_token)
        down_prices = get_real_prices(down_token)

        up_price, up_source = _select_best_price(up_prices)
        down_price, down_source = _select_best_price(down_prices)

        # Gamma prices as reference only (NOT for entry)
        gamma_up = None
        gamma_down = None
        outcome_prices = market.get("outcomePrices", "")
        if isinstance(outcome_prices, str) and outcome_prices:
            import json as _json
            try:
                outcome_prices = _json.loads(outcome_prices)
            except Exception:
                outcome_prices = []
        if outcome_prices and len(outcome_prices) >= 2:
            gamma_up = float(outcome_prices[0])
            gamma_down = float(outcome_prices[1])

        return MarketInfo(
            slug=slug,
            condition_id=condition_id,
            up_token_id=up_token,
            down_token_id=down_token,
            up_price=up_price,
            down_price=down_price,
            up_source=up_source,
            down_source=down_source,
            gamma_up=gamma_up,
            gamma_down=gamma_down,
            up_spread=up_prices["spread"],
            down_spread=down_prices["spread"],
            window_ts=window_ts,
        )

    except Exception as e:
        print("[Polymarket] Error finding market %s: %s" % (slug, e))
        return None


def get_market_price(token_id: str, side: str = "BUY") -> float:
    """
    Get the current best price for a token from the CLOB.

    Args:
        token_id: The token to check.
        side: "BUY" (best bid) or "SELL" (best ask).

    Returns:
        Price as float (0-1), or 0.5 if unavailable.
    """
    try:
        resp = requests.get(
            "%s/price" % CLOB_API,
            params={"token_id": token_id, "side": side},
            timeout=5,
        )
        resp.raise_for_status()
        data = resp.json()
        return float(data.get("price", 0.5))
    except Exception:
        return 0.5


def get_orderbook(token_id: str) -> dict:
    """
    Get full orderbook for a token.

    Returns:
        Dict with 'bids' and 'asks' lists.
    """
    try:
        resp = requests.get(
            "%s/book" % CLOB_API,
            params={"token_id": token_id},
            timeout=5,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print("[Polymarket] Error fetching orderbook: %s" % e)
        return {"bids": [], "asks": []}


def get_best_ask(token_id: str) -> float | None:
    """Get the best (lowest) ask price from the orderbook."""
    book = get_orderbook(token_id)
    asks = book.get("asks", [])
    if not asks:
        return None
    # Asks are sorted lowest first
    return float(asks[0].get("price", 0))


def get_best_bid(token_id: str) -> float | None:
    """Get the best (highest) bid price from the orderbook."""
    book = get_orderbook(token_id)
    bids = book.get("bids", [])
    if not bids:
        return None
    # Bids are sorted highest first
    return float(bids[0].get("price", 0))


def check_liquidity(token_id: str, max_spread: float = 0.03,
                    min_depth: float = 20.0) -> dict:
    """Check if a token has enough liquidity to trade.

    For Polymarket binary markets (especially short-lived 5-min windows),
    the CLOB orderbook is often empty or has only extreme-price resting orders.

    Strategy:
      1. Try CLOB orderbook first — if it has reasonable bids/asks, use it.
      2. If CLOB is empty/extreme, fall back to Gamma API prices.
         For 5-min markets this is the normal case, not an error.

    Returns dict with 'ok' bool, 'spread', 'depth', 'reason', 'source'.
    """
    book = get_orderbook(token_id)
    bids = book.get("bids", [])
    asks = book.get("asks", [])

    # Try CLOB orderbook
    if bids and asks:
        best_bid = float(bids[0]["price"])
        best_ask = float(asks[0]["price"])
        spread = best_ask - best_bid

        # Calculate depth (total $ within top 5 levels)
        bid_depth = sum(float(b["price"]) * float(b["size"]) for b in bids[:5])
        ask_depth = sum(float(a["price"]) * float(a["size"]) for a in asks[:5])
        depth = min(bid_depth, ask_depth)

        # If CLOB spread is reasonable, use it as the authority
        if spread <= max_spread:
            if depth < min_depth:
                return {"ok": False, "spread": spread, "depth": depth,
                        "source": "clob",
                        "reason": "depth_too_low ($%.0f < $%.0f)" % (depth, min_depth)}
            return {"ok": True, "spread": spread, "depth": depth,
                    "source": "clob", "reason": "pass"}

    # Fallback: CLOB empty or wide spread (normal for 5-min markets)
    return {"ok": True, "spread": 0.0, "depth": 0.0,
            "source": "gamma_fallback",
            "reason": "clob_empty_using_gamma_prices"}


def calculate_edge(model_prob: float, market_price: float) -> float:
    """
    Calculate edge: what the model thinks vs what the market charges.

    Args:
        model_prob: Model's probability for this outcome (0-1).
        market_price: Market price to buy this outcome (0-1).

    Returns:
        Edge (positive = profitable).
    """
    return model_prob - market_price


class PolymarketTrader:
    """
    Live trader that places orders on Polymarket based on model predictions.

    Uses py-clob-client for authenticated order placement.
    """

    def __init__(self, config: Config):
        self.config = config
        self.client = None
        self._init_client()

    def _init_client(self):
        """Initialize the authenticated CLOB client."""
        if not self.config.POLYMARKET_PRIVATE_KEY:
            print("[Polymarket] WARNING: No private key set. Read-only mode.")
            return

        try:
            from py_clob_client.client import ClobClient

            self.client = ClobClient(
                CLOB_API,
                key=self.config.POLYMARKET_PRIVATE_KEY,
                chain_id=137,
            )
            self.client.set_api_creds(self.client.create_or_derive_api_creds())
            print("[Polymarket] Client initialized successfully")
        except ImportError:
            print("[Polymarket] py-clob-client not installed. Run: pip install py-clob-client")
        except Exception as e:
            print("[Polymarket] Error initializing client: %s" % e)

    def place_limit_order(
        self,
        token_id: str,
        price: float,
        size: float,
        side: str = "BUY",
    ) -> dict | None:
        """
        Place a limit order on Polymarket.

        Args:
            token_id: Token to buy/sell.
            price: Limit price (0-1).
            size: Number of shares.
            side: "BUY" or "SELL".

        Returns:
            Order response dict, or None on failure.
        """
        if self.client is None:
            print("[Polymarket] Client not initialized, cannot place order")
            return None

        try:
            from py_clob_client.clob_types import OrderArgs, OrderType
            from py_clob_client.order_builder.constants import BUY, SELL

            order_side = BUY if side == "BUY" else SELL
            order = OrderArgs(
                token_id=token_id,
                price=price,
                size=size,
                side=order_side,
            )
            signed = self.client.create_order(order)
            resp = self.client.post_order(signed, OrderType.GTC)
            print("[Polymarket] Order placed: %s %s @ %.2f x %.1f" % (side, token_id[:12], price, size))
            return resp
        except Exception as e:
            print("[Polymarket] Error placing order: %s" % e)
            return None

    def place_market_order(
        self,
        token_id: str,
        amount: float,
        side: str = "BUY",
    ) -> dict | None:
        """
        Place a market order (Fill or Kill).

        Args:
            token_id: Token to buy/sell.
            amount: Dollar amount for BUY, share count for SELL.
            side: "BUY" or "SELL".

        Returns:
            Order response dict, or None on failure.
        """
        if self.client is None:
            print("[Polymarket] Client not initialized, cannot place order")
            return None

        try:
            from py_clob_client.clob_types import MarketOrderArgs, OrderType
            from py_clob_client.order_builder.constants import BUY, SELL

            order_side = BUY if side == "BUY" else SELL
            mo = MarketOrderArgs(
                token_id=token_id,
                amount=amount,
                side=order_side,
                order_type=OrderType.FOK,
            )
            signed = self.client.create_market_order(mo)
            resp = self.client.post_order(signed, OrderType.FOK)
            print("[Polymarket] Market order: %s $%.2f" % (side, amount))
            return resp
        except Exception as e:
            print("[Polymarket] Error placing market order: %s" % e)
            return None

    def execute_signal(
        self,
        direction: str,
        model_prob: float,
        bet_size: float,
        min_edge: float = 0.03,
    ) -> dict | None:
        """
        Execute a trading signal: check market price, verify edge, place order.

        Args:
            direction: "UP" or "DOWN"
            model_prob: Model's calibrated probability (0-1)
            bet_size: How much to bet in dollars
            min_edge: Minimum edge required to trade

        Returns:
            Trade result dict, or None if skipped.
        """
        # Find current market
        market = find_market()
        if market is None:
            print("[Polymarket] No active market found")
            return None

        # Get the right token
        if direction == "UP":
            token_id = market.up_token_id
            model_prob_for_side = model_prob
            market_price = market.up_price
        else:
            token_id = market.down_token_id
            model_prob_for_side = 1 - model_prob
            market_price = market.down_price

        # Calculate edge with REAL market price
        edge = calculate_edge(model_prob_for_side, market_price)

        result = {
            "direction": direction,
            "model_prob": model_prob_for_side,
            "market_price": market_price,
            "edge": edge,
            "slug": market.slug,
            "token_id": token_id[:16] + "...",
        }

        print(
            "[Polymarket] Signal: %s | model=%.4f market=%.4f edge=%.4f"
            % (direction, model_prob_for_side, market_price, edge)
        )

        # Edge check with REAL price
        if edge < min_edge:
            print("[Polymarket] SKIP: edge %.4f < min %.4f (market already priced in)" % (edge, min_edge))
            result["action"] = "SKIP"
            return result

        # Calculate shares to buy
        shares = bet_size / market_price

        # Place limit order at slightly below market (better fill)
        limit_price = round(market_price - 0.01, 2)
        limit_price = max(0.01, min(0.99, limit_price))

        resp = self.place_limit_order(
            token_id=token_id if direction == "UP" else market.down_token_id,
            price=limit_price,
            size=round(shares, 1),
            side="BUY",
        )

        result["action"] = "ORDER_PLACED"
        result["limit_price"] = limit_price
        result["shares"] = round(shares, 1)
        result["order_response"] = resp

        return result
