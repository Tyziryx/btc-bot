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
          <CardTitle className="text-sm text-muted-foreground">PnL by Direction</CardTitle>
        </CardHeader>
        <CardContent className="h-56"><Skeleton className="h-full w-full" /></CardContent>
      </Card>
    );
  }

  const trades = data.trades || [];
  if (!trades.length) {
    return (
      <Card>
        <CardHeader className="pb-1">
          <CardTitle className="text-sm text-muted-foreground">PnL by Direction</CardTitle>
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
    if (t.direction === "UP") upCum += t.pnl;
    else downCum += t.pnl;
    return {
      idx: i + 1,
      up: Number(upCum.toFixed(2)),
      down: Number(downCum.toFixed(2)),
    };
  });

  return (
    <Card>
      <CardHeader className="pb-1">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm text-muted-foreground">PnL by Direction</CardTitle>
          <div className="flex gap-3 text-xs tabular-nums">
            <span className="text-emerald-400">UP: ${upCum >= 0 ? "+" : ""}{upCum.toFixed(2)}</span>
            <span className="text-red-400">DOWN: ${downCum >= 0 ? "+" : ""}{downCum.toFixed(2)}</span>
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
              formatter={(value: any, name: string) => [`$${Number(value).toFixed(2)}`, name === "up" ? "UP" : "DOWN"]}
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
