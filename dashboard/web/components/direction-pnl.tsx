"use client";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useTrades } from "@/hooks/use-trades";
import {
  AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer,
  CartesianGrid, ReferenceLine,
} from "recharts";

export function DirectionPnl() {
  const { data } = useTrades(200);

  if (!data) {
    return (
      <Card>
        <CardHeader className="pb-1">
          <CardTitle className="text-sm text-muted-foreground">P&L by Leg1 Side</CardTitle>
        </CardHeader>
        <CardContent className="h-56"><Skeleton className="h-full w-full" /></CardContent>
      </Card>
    );
  }

  const trades = data.trades || [];
  const isArb = trades.length > 0 && "status" in trades[0];
  const title = isArb ? "P&L by Leg1 Side" : "PnL by Direction";

  if (!trades.length) {
    return (
      <Card>
        <CardHeader className="pb-1">
          <CardTitle className="text-sm text-muted-foreground">{title}</CardTitle>
        </CardHeader>
        <CardContent className="h-56 flex items-center justify-center text-muted-foreground text-sm">
          No trades yet
        </CardContent>
      </Card>
    );
  }

  let upCum = 0;
  let downCum = 0;

  const chartData = trades.map((t: any, i: number) => {
    // Arb: use leg1_side + profit. Paper: use direction + pnl.
    const side = isArb ? t.leg1_side : t.direction;
    const pnl = isArb ? (t.profit ?? 0) : (t.pnl ?? 0);

    if (side === "UP") upCum += pnl;
    else if (side === "DOWN") downCum += pnl;

    return {
      idx: i + 1,
      up: Number(upCum.toFixed(4)),
      down: Number(downCum.toFixed(4)),
    };
  });

  return (
    <Card>
      <CardHeader className="pb-1">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm text-muted-foreground">{title}</CardTitle>
          <div className="flex gap-3 text-xs tabular-nums">
            <span className={upCum >= 0 ? "text-emerald-400" : "text-red-400"}>
              UP: {upCum >= 0 ? "+" : ""}${upCum.toFixed(isArb ? 4 : 2)}
            </span>
            <span className={downCum >= 0 ? "text-emerald-400" : "text-red-400"}>
              DOWN: {downCum >= 0 ? "+" : ""}${downCum.toFixed(isArb ? 4 : 2)}
            </span>
          </div>
        </div>
      </CardHeader>
      <CardContent className="h-56">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={chartData} margin={{ top: 5, right: 10, bottom: 5, left: 10 }}>
            <defs>
              <linearGradient id="upGrad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#34d399" stopOpacity={0.2} />
                <stop offset="95%" stopColor="#34d399" stopOpacity={0} />
              </linearGradient>
              <linearGradient id="downGrad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#f87171" stopOpacity={0.2} />
                <stop offset="95%" stopColor="#f87171" stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
            <XAxis dataKey="idx" tick={{ fill: "hsl(var(--muted-foreground))", fontSize: 9 }} tickLine={false} axisLine={false} />
            <YAxis tick={{ fill: "hsl(var(--muted-foreground))", fontSize: 9 }} tickLine={false} axisLine={false} tickFormatter={(v: number) => `$${v}`} />
            <Tooltip
              contentStyle={{ background: "hsl(var(--card))", border: "1px solid hsl(var(--border))", borderRadius: 8, fontSize: 12 }}
              formatter={(value: any, name: any) => [`$${Number(value).toFixed(4)}`, name === "up" ? "UP" : "DOWN"]}
            />
            <ReferenceLine y={0} stroke="hsl(var(--muted-foreground))" strokeDasharray="4 4" />
            <Area type="monotone" dataKey="up" stroke="#34d399" fill="url(#upGrad)" strokeWidth={2} dot={false} name="UP" />
            <Area type="monotone" dataKey="down" stroke="#f87171" fill="url(#downGrad)" strokeWidth={2} dot={false} name="DOWN" />
          </AreaChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  );
}
