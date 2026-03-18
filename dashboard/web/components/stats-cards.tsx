"use client";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useStats } from "@/hooks/use-trades";

function formatUsd(n: number): string {
  const sign = n >= 0 ? "+" : "";
  return `${sign}$${Math.abs(n).toFixed(2)}`;
}

function formatPct(n: number): string {
  const sign = n >= 0 ? "+" : "";
  return `${sign}${n.toFixed(1)}%`;
}

export function StatsCards() {
  const { data } = useStats();
  if (!data) return <div className="text-zinc-500">Loading...</div>;

  const cards = [
    { title: "Capital", value: `$${data.capital}`, sub: `started $${data.initial_capital}` },
    { title: "ROI", value: formatPct(data.roi), color: data.roi >= 0 ? "text-emerald-400" : "text-red-400" },
    { title: "PnL", value: formatUsd(data.total_pnl), color: data.total_pnl >= 0 ? "text-emerald-400" : "text-red-400" },
    { title: "Win Rate", value: `${data.win_rate}%`, sub: `${data.wins}W / ${data.losses}L` },
    { title: "Drawdown", value: formatPct(-data.max_drawdown), color: "text-amber-400" },
    { title: "Profit Factor", value: data.profit_factor.toFixed(2), color: data.profit_factor >= 1 ? "text-emerald-400" : "text-red-400" },
  ];

  return (
    <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
      {cards.map((c) => (
        <Card key={c.title} className="bg-zinc-900 border-zinc-800">
          <CardHeader className="pb-1 pt-3 px-4">
            <CardTitle className="text-xs text-zinc-500 uppercase tracking-wider">{c.title}</CardTitle>
          </CardHeader>
          <CardContent className="px-4 pb-3">
            <p className={`text-xl font-bold ${c.color || "text-zinc-100"}`}>{c.value}</p>
            {c.sub && <p className="text-xs text-zinc-500 mt-0.5">{c.sub}</p>}
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
