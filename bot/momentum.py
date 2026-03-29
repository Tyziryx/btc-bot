"""
Cross-window momentum signal.

Tracks outcomes of past windows (UP/DOWN resolution) and produces
a directional multiplier for the confidence score.
"""
from __future__ import annotations

import json
import os
from collections import deque


class SequenceMomentum:
    """
    Tracks the last N window resolutions and computes a directional bias.

    multiplier("UP") returns:
      1.15  — if recent windows lean UP (momentum confirms)
      0.85  — if recent windows lean DOWN (counter-trend)
      1.0   — neutral / insufficient data
    """

    def __init__(self, lookback: int = 3):
        self.lookback = lookback
        self._history: deque[dict] = deque(maxlen=lookback)

    # ── Population ───────────────────────────────────────────────────────────

    def load_from_jsonl(self, path: str) -> None:
        """Seed history from a completed arb_trades.jsonl file."""
        if not os.path.exists(path):
            return

        window_outcomes: dict[int, str] = {}
        try:
            with open(path) as f:
                for raw in f:
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        t = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    wid = t.get("window_id")
                    status = t.get("status", "")
                    side = t.get("side", "")
                    if not wid:
                        continue
                    if status == "win" and side:
                        # Winning UP means UP resolved; winning DOWN means DOWN resolved
                        window_outcomes[wid] = side
                    elif status == "lose" and side:
                        # Losing UP means DOWN actually won
                        window_outcomes[wid] = "DOWN" if side == "UP" else "UP"
                    # abandoned → no clean signal, skip
        except OSError:
            return

        for wid in sorted(window_outcomes)[-self.lookback:]:
            self._history.append({"window_id": wid, "resolution": window_outcomes[wid]})

    def add_resolution(self, window_id: int, resolution: str) -> None:
        """Record a completed window outcome. Call after win/lose resolve."""
        if resolution not in ("UP", "DOWN"):
            return
        self._history.append({"window_id": window_id, "resolution": resolution})

    # ── Signal ───────────────────────────────────────────────────────────────

    def score(self) -> float:
        """
        Weighted momentum score in [-1.0, +1.0].
        Most recent window weighted 0.50, then 0.33, then 0.17.
        """
        items = list(self._history)
        if len(items) < 2:
            return 0.0
        weights = [0.50, 0.33, 0.17][: len(items)]
        total = sum(weights)
        raw = sum(
            w * (1.0 if item["resolution"] == "UP" else -1.0)
            for w, item in zip(weights, reversed(items))
        )
        return round(raw / total, 3)

    def multiplier(self, direction: str) -> float:
        """
        Confidence multiplier when entering `direction`.
        Returns 1.15 (boost), 0.85 (penalty), or 1.0 (neutral).
        """
        s = self.score()
        signal_dir = 1.0 if direction == "UP" else -1.0
        alignment = s * signal_dir
        if alignment > 0.3:
            return 1.15
        if alignment < -0.3:
            return 0.85
        return 1.0

    def __repr__(self) -> str:
        return "SequenceMomentum(score=%.3f, history=%r)" % (self.score(), list(self._history))
