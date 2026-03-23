"use client";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useStats } from "@/hooks/use-trades";

export function StatsCards() {
  const { data } = useStats();

  if (!data) {
    return (
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
        {Array.from({ length: 6 }).map((_, i) => (
          <Card key={i}>
            <CardHeader className="pb-1 pt-3 px-4">
              <Skeleton className="h-3 w-16" />
            </CardHeader>
            <CardContent className="px-4 pb-3">
              <Skeleton className="h-7 w-24" />
            </CardContent>
          </Card>
        ))}
      </div>
    );
  }

  const isArb = data.mode === "arb";

  const cards = [
    {
      title: "Capital",
      value: `$${data.capital.toFixed(2)}`,
      sub: `started $${data.initial_capital.toFixed(2)}`,
      color: data.capital >= data.initial_capital ? "text-emerald-400" : "text-red-400",
    },
    {
      title: "ROI",
      value: `${data.roi >= 0 ? "+" : ""}${data.roi.toFixed(1)}%`,
      color: data.roi >= 0 ? "text-emerald-400" : "text-red-400",
    },
    {
      title: "Total PnL",
      value: `${data.total_pnl >= 0 ? "+" : ""}$${Math.abs(data.total_pnl).toFixed(isArb ? 4 : 2)}`,
      color: data.total_pnl >= 0 ? "text-emerald-400" : "text-red-400",
    },
    isArb
      ? {
          title: "Arb Rate",
          value: `${data.completed ?? 0}/${data.total_trades}`,
          sub: `${data.completed ?? 0} complete, ${data.abandoned ?? 0} abandoned`,
          color: (data.completed ?? 0) > (data.abandoned ?? 0) ? "text-emerald-400" : "text-amber-400",
        }
      : {
          title: "Win Rate",
          value: `${data.win_rate.toFixed(1)}%`,
          sub: `${data.wins}W / ${data.losses}L (${data.total_trades} trades)`,
          color: data.win_rate >= 55 ? "text-emerald-400" : data.win_rate >= 50 ? "text-amber-400" : "text-red-400",
        },
    {
      title: "Max Drawdown",
      value: `-${data.max_drawdown.toFixed(1)}%`,
      color: data.max_drawdown > 10 ? "text-red-400" : "text-amber-400",
    },
    isArb
      ? {
          title: "Avg Profit",
          value: data.avg_win > 0 ? `$${data.avg_win.toFixed(4)}` : "\u2014",
          sub: data.total_trades > 0 ? `${data.total_trades} total positions` : undefined,
          color: data.avg_win > 0 ? "text-emerald-400" : "text-muted-foreground",
        }
      : {
          title: "Profit Factor",
          value: data.profit_factor > 0 ? data.profit_factor.toFixed(2) : "\u2014",
          sub: data.avg_win > 0 ? `avg W +$${data.avg_win.toFixed(2)} / L $${Math.abs(data.avg_loss).toFixed(2)}` : undefined,
          color: data.profit_factor >= 1.5 ? "text-emerald-400" : data.profit_factor >= 1 ? "text-amber-400" : "text-red-400",
        },
  ];

  return (
    <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
      {cards.map((c) => (
        <Card key={c.title}>
          <CardHeader className="pb-1 pt-3 px-4">
            <CardTitle className="text-[10px] text-muted-foreground uppercase tracking-widest font-medium">
              {c.title}
            </CardTitle>
          </CardHeader>
          <CardContent className="px-4 pb-3">
            <p className={`text-xl font-bold tabular-nums ${c.color || "text-foreground"}`}>{c.value}</p>
            {c.sub && <p className="text-[10px] text-muted-foreground mt-0.5">{c.sub}</p>}
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
