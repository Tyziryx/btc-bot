"use client";
import { useStats } from "@/hooks/use-trades";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer,
  ReferenceLine, CartesianGrid
} from "recharts";

export function PnlChart() {
  const { data } = useStats();

  if (!data) {
    return (
      <Card>
        <CardHeader><CardTitle className="text-sm text-muted-foreground">Capital Curve</CardTitle></CardHeader>
        <CardContent className="h-72"><Skeleton className="h-full w-full" /></CardContent>
      </Card>
    );
  }

  if (!data.capital_curve?.length) {
    return (
      <Card>
        <CardHeader><CardTitle className="text-sm text-muted-foreground">Capital Curve</CardTitle></CardHeader>
        <CardContent className="h-72 flex items-center justify-center text-muted-foreground text-sm">
          No trades yet
        </CardContent>
      </Card>
    );
  }

  const initial = data.initial_capital || 100;
  const chartData = data.capital_curve.map((p: any, i: number) => ({
    idx: i + 1,
    capital: Number(p.capital.toFixed(2)),
    ts: p.ts
      ? new Date(p.ts).toLocaleTimeString("en-US", { hour12: false, hour: "2-digit", minute: "2-digit" })
      : "",
  }));

  const current = chartData[chartData.length - 1]?.capital ?? initial;
  const isUp = current >= initial;
  const minCap = Math.min(...chartData.map((d: any) => d.capital));
  const maxCap = Math.max(...chartData.map((d: any) => d.capital));

  return (
    <Card>
      <CardHeader className="pb-1">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm text-muted-foreground">Capital Curve</CardTitle>
          <span className={`text-lg font-bold tabular-nums ${isUp ? "text-emerald-400" : "text-red-400"}`}>
            ${current.toFixed(2)}
          </span>
        </div>
      </CardHeader>
      <CardContent className="h-72">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={chartData} margin={{ top: 5, right: 10, bottom: 5, left: 10 }}>
            <defs>
              <linearGradient id="capitalGrad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor={isUp ? "#34d399" : "#f87171"} stopOpacity={0.25} />
                <stop offset="95%" stopColor={isUp ? "#34d399" : "#f87171"} stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
            <XAxis dataKey="ts" tick={{ fill: "hsl(var(--muted-foreground))", fontSize: 9 }} tickLine={false} axisLine={false} />
            <YAxis
              domain={[Math.floor(minCap - 1), Math.ceil(maxCap + 1)]}
              tick={{ fill: "hsl(var(--muted-foreground))", fontSize: 9 }}
              tickLine={false} axisLine={false}
              tickFormatter={(v: number) => `$${v}`}
            />
            <Tooltip
              contentStyle={{ background: "hsl(var(--card))", border: "1px solid hsl(var(--border))", borderRadius: 8, fontSize: 12 }}
              labelStyle={{ color: "hsl(var(--muted-foreground))" }}
              formatter={(value: any) => [`$${Number(value).toFixed(2)}`, "Capital"]}
            />
            <ReferenceLine y={initial} stroke="hsl(var(--muted-foreground))" strokeDasharray="4 4" />
            <Area
              type="monotone" dataKey="capital" stroke={isUp ? "#34d399" : "#f87171"}
              fill="url(#capitalGrad)" strokeWidth={2} dot={false}
            />
          </AreaChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  );
}
