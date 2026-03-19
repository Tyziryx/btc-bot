"use client";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useTrades } from "@/hooks/use-trades";
import {
  LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer,
  ReferenceLine, CartesianGrid,
} from "recharts";

export function WinRateChart() {
  const { data } = useTrades(200);

  if (!data) {
    return (
      <Card>
        <CardHeader className="pb-1">
          <CardTitle className="text-sm text-muted-foreground">Win Rate Rolling (20)</CardTitle>
        </CardHeader>
        <CardContent className="h-56"><Skeleton className="h-full w-full" /></CardContent>
      </Card>
    );
  }

  const trades = data.trades || [];
  if (trades.length < 5) {
    return (
      <Card>
        <CardHeader className="pb-1">
          <CardTitle className="text-sm text-muted-foreground">Win Rate Rolling (20)</CardTitle>
        </CardHeader>
        <CardContent className="h-56 flex items-center justify-center text-muted-foreground text-sm">
          Need 5+ trades for rolling window
        </CardContent>
      </Card>
    );
  }

  const window = 20;
  const chartData = trades.map((_: any, i: number) => {
    const start = Math.max(0, i - window + 1);
    const slice = trades.slice(start, i + 1);
    const wr = slice.filter((t: any) => t.won).length / slice.length * 100;
    return { idx: i + 1, wr: Number(wr.toFixed(1)) };
  });

  const latest = chartData[chartData.length - 1]?.wr ?? 0;

  return (
    <Card>
      <CardHeader className="pb-1">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm text-muted-foreground">Win Rate Rolling (20)</CardTitle>
          <span className={`text-sm font-bold tabular-nums ${latest >= 55 ? "text-emerald-400" : latest >= 50 ? "text-amber-400" : "text-red-400"}`}>
            {latest.toFixed(0)}%
          </span>
        </div>
      </CardHeader>
      <CardContent className="h-56">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={chartData} margin={{ top: 5, right: 10, bottom: 5, left: 10 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
            <XAxis dataKey="idx" tick={{ fill: "hsl(var(--muted-foreground))", fontSize: 9 }} tickLine={false} axisLine={false} />
            <YAxis domain={[30, 80]} tick={{ fill: "hsl(var(--muted-foreground))", fontSize: 9 }} tickLine={false} axisLine={false} tickFormatter={(v: number) => `${v}%`} />
            <Tooltip
              contentStyle={{ background: "hsl(var(--card))", border: "1px solid hsl(var(--border))", borderRadius: 8, fontSize: 12 }}
              formatter={(value: any) => [`${Number(value).toFixed(1)}%`, "WR"]}
            />
            <ReferenceLine y={50} stroke="#f59e0b" strokeDasharray="4 4" label={{ value: "50%", fill: "#f59e0b", fontSize: 10 }} />
            <Line type="monotone" dataKey="wr" stroke="#34d399" strokeWidth={2} dot={false} />
          </LineChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  );
}
