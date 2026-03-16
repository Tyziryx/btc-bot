"""
Model drift detector - monitors rolling win rate and alerts when
the model's predictions no longer match reality.

Levels:
  - ok: WR >= 52% (profitable)
  - WARNING: WR < 52% (below profitability threshold)
  - CRITICAL: WR < 48% (stop trading, model is broken)
"""


class DriftDetector:
    def __init__(self, window: int = 100, critical_threshold: float = 0.48,
                 warning_threshold: float = 0.52):
        self.window = window
        self.critical_threshold = critical_threshold
        self.warning_threshold = warning_threshold
        self.results: list[bool] = []

    def update(self, won: bool):
        self.results.append(won)
        if len(self.results) > self.window * 2:
            self.results = self.results[-self.window * 2:]

    def check(self) -> dict:
        if len(self.results) < 30:
            return {"status": "warming_up", "n": len(self.results),
                    "win_rate": 0.0, "should_stop": False, "should_retrain": False}

        recent = self.results[-self.window:]
        n = len(recent)
        wins = sum(recent)
        wr = wins / n

        status = "ok"
        if wr < self.critical_threshold:
            status = "CRITICAL"
        elif wr < self.warning_threshold:
            status = "WARNING"

        return {
            "status": status,
            "win_rate": round(wr, 4),
            "n": n,
            "should_stop": status == "CRITICAL",
            "should_retrain": status in ("CRITICAL", "WARNING"),
        }

    def summary(self) -> str:
        info = self.check()
        if info["status"] == "warming_up":
            return "warming up (%d/%d trades)" % (info["n"], self.window)
        return "%s | WR=%.1f%% (%d trades)" % (
            info["status"], info["win_rate"] * 100, info["n"])
