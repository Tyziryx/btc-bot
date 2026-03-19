"use client";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useTrades } from "@/hooks/use-trades";
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer,
  CartesianGrid, Cell,
} from "recharts";

export function EntryDistribution() {
  const { data } = useTrades(200);

  if (!data) {
    return (
      <Card>
        <CardHeader className="pb-1">
          <CardTitle className="text-sm text-muted-foreground">Entry Price Distribution</CardTitle>
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
          <CardTitle className="text-sm text-muted-foreground">Entry Price Distribution</CardTitle>
        </CardHeader>
        <CardContent className="h-56 flex items-center justify-center text-muted-foreground text-sm">
          No trades yet
        </CardContent>
      </Card>
    );
  }

  const prices = trades.map((t: any) => t.entry_price).filter(Boolean);
  const minP = Math.floor(Math.min(...prices) * 100) / 100;
  const maxP = Math.ceil(Math.max(...prices) * 100) / 100;

  const bins: { label: string; min: number; max: number; count: number; goodPayoff: boolean }[] = [];
  for (let p = minP; p < maxP; p = Number((p + 0.01).toFixed(2))) {
    const upper = Number((p + 0.01).toFixed(2));
    const count = prices.filter((x: number) => x >= p && x < upper).length;
    bins.push({
      label: `${p.toFixed(2)}`,
      min: p,
      max: upper,
      count,
      goodPayoff: p < 0.52,
    });
  }

  return (
    <Card>
      <CardHeader className="pb-1">
        <CardTitle className="text-sm text-muted-foreground">Entry Price Distribution</CardTitle>
      </CardHeader>
      <CardContent className="h-56">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={bins} margin={{ top: 5, right: 10, bottom: 5, left: 10 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
            <XAxis dataKey="label" tick={{ fill: "hsl(var(--muted-foreground))", fontSize: 9 }} tickLine={false} axisLine={false} />
            <YAxis tick={{ fill: "hsl(var(--muted-foreground))", fontSize: 9 }} tickLine={false} axisLine={false} />
            <Tooltip
              contentStyle={{ background: "hsl(var(--card))", border: "1px solid hsl(var(--border))", borderRadius: 8, fontSize: 12 }}
              formatter={(value: any) => [value, "Trades"]}
            />
            <Bar dataKey="count" radius={[3, 3, 0, 0]}>
              {bins.map((b, i) => (
                <Cell key={i} fill={b.goodPayoff ? "#34d399" : "#f59e0b"} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  );
}
