import random

import numpy as np
import pandas as pd


class BacktestEngine:
    FILL_RATES = {
        (0.45, 1.00): 0.95,
        (0.40, 0.45): 0.85,
        (0.35, 0.40): 0.65,
        (0.00, 0.35): 0.40,
    }

    def __init__(
        self,
        initial_capital: float = 100.0,
        min_confidence: float = 0.60,
        min_edge: float = 0.03,
        max_bet_fraction: float = 0.02,
        max_bet: float = 40.0,
        min_bet: float = 2.0,
        daily_stop_loss: float = 0.05,
        max_drawdown: float = 0.15,
        circuit_breaker_losses: int = 5,
    ):
        self.initial_capital = initial_capital
        self.min_confidence = min_confidence
        self.min_edge = min_edge
        self.max_bet_fraction = max_bet_fraction
        self.max_bet = max_bet
        self.min_bet = min_bet
        self.daily_stop_loss = daily_stop_loss
        self.max_drawdown = max_drawdown
        self.circuit_breaker_losses = circuit_breaker_losses

    def _get_fill_rate(self, entry_price: float) -> float:
        for (lo, hi), rate in self.FILL_RATES.items():
            if lo <= entry_price < hi:
                return rate
        return 0.5

    def _calculate_entry_price(self, prob: float) -> float:
        if prob > 0.5:
            fair_value = prob
        else:
            fair_value = 1 - prob
        entry = fair_value - self.min_edge
        entry += random.uniform(-0.005, 0.005)
        return max(0.25, min(entry, 0.55))

    def _quarter_kelly(self, capital, confidence, win_rate, entry_price):
        b = (1.0 - entry_price) / entry_price
        p = win_rate
        kelly = (p * b - (1 - p)) / b if b > 0 else 0
        kelly = max(kelly, 0)
        fraction = kelly / 4 * confidence
        bet = capital * fraction
        return max(self.min_bet, min(bet, capital * self.max_bet_fraction, self.max_bet))

    def run(self, data: pd.DataFrame) -> dict:
        capital = self.initial_capital
        peak_capital = capital
        trades = []
        capital_curve = [capital]
        consecutive_losses = 0
        daily_start_capital = capital
        current_day = None
        paused_until = None

        for ts, row in data.iterrows():
            prob = row["prob_calibrated"]
            label = int(row["label"])

            day = ts.date()
            if day != current_day:
                current_day = day
                daily_start_capital = capital

            if paused_until is not None and ts < paused_until:
                capital_curve.append(capital)
                continue
            paused_until = None

            if daily_start_capital > 0 and (daily_start_capital - capital) / daily_start_capital > self.daily_stop_loss:
                capital_curve.append(capital)
                continue

            if peak_capital > 0 and (peak_capital - capital) / peak_capital > self.max_drawdown:
                capital_curve.append(capital)
                continue

            confidence = abs(prob - 0.5) * 2
            if confidence < self.min_confidence:
                capital_curve.append(capital)
                continue

            entry_price = self._calculate_entry_price(prob)
            fair_value = prob if prob > 0.5 else (1 - prob)

            if fair_value - entry_price < self.min_edge:
                capital_curve.append(capital)
                continue

            fill_rate = self._get_fill_rate(entry_price)
            if random.random() > fill_rate:
                capital_curve.append(capital)
                continue

            rolling_wr = 0.55
            if len(trades) >= 20:
                recent = trades[-20:]
                rolling_wr = sum(1 for t in recent if t["result"] == "win") / len(recent)
                rolling_wr = max(rolling_wr, 0.50)

            bet_size = self._quarter_kelly(capital, confidence, rolling_wr, entry_price)
            if bet_size > capital:
                capital_curve.append(capital)
                continue

            predicted_up = prob > 0.5
            actual_up = label == 1
            win = predicted_up == actual_up

            if win:
                pnl = bet_size * (1.0 - entry_price) / entry_price
                consecutive_losses = 0
            else:
                pnl = -bet_size
                consecutive_losses += 1

            capital += pnl
            capital = max(capital, 0)
            peak_capital = max(peak_capital, capital)

            trades.append({
                "timestamp": ts,
                "direction": "UP" if predicted_up else "DOWN",
                "confidence": confidence,
                "entry_price": entry_price,
                "bet_size": bet_size,
                "result": "win" if win else "loss",
                "pnl": pnl,
                "capital": capital,
            })

            if consecutive_losses >= self.circuit_breaker_losses:
                paused_until = ts + pd.Timedelta(minutes=30)
                consecutive_losses = 0

            capital_curve.append(capital)

        if not trades:
            return {
                "total_trades": 0, "win_rate": 0.0, "final_capital": capital,
                "roi": 0.0, "max_drawdown": 0.0, "profit_factor": 0.0,
                "sharpe_ratio": 0.0, "capital_curve": capital_curve, "trades": [],
            }

        wins = [t for t in trades if t["result"] == "win"]
        losses = [t for t in trades if t["result"] == "loss"]
        gross_profit = sum(t["pnl"] for t in wins) if wins else 0
        gross_loss = abs(sum(t["pnl"] for t in losses)) if losses else 1

        curve = np.array(capital_curve)
        running_max = np.maximum.accumulate(curve)
        drawdowns = np.where(running_max > 0, (running_max - curve) / running_max, 0)
        max_dd = drawdowns.max()

        pnls = [t["pnl"] for t in trades]
        if len(pnls) > 1 and np.std(pnls) > 0:
            sharpe = np.mean(pnls) / np.std(pnls) * np.sqrt(252 * 24 * 12)
        else:
            sharpe = 0.0

        return {
            "total_trades": len(trades),
            "win_rate": len(wins) / len(trades),
            "final_capital": capital,
            "roi": (capital - self.initial_capital) / self.initial_capital,
            "max_drawdown": max_dd,
            "profit_factor": gross_profit / gross_loss if gross_loss > 0 else float("inf"),
            "sharpe_ratio": sharpe,
            "capital_curve": capital_curve,
            "trades": trades,
        }
