"use client";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useTrades } from "@/hooks/use-trades";
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer,
  CartesianGrid, Cell, ReferenceLine,
} from "recharts";

export function EntryDistribution() {
  const { data } = useTrades(200);

  if (!data) {
    return (
      <Card>
        <CardHeader className="pb-1">
          <CardTitle className="text-sm text-muted-foreground">Cost Distribution</CardTitle>
        </CardHeader>
        <CardContent className="h-56"><Skeleton className="h-full w-full" /></CardContent>
      </Card>
    );
  }

  const trades = data.trades || [];
  const isArb = trades.length > 0 && "status" in trades[0];
  const title = isArb ? "Combined Cost Distribution" : "Entry Price Distribution";

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

  if (isArb) {
    // Arb mode: Combined Cost Distribution (completed arbs only)
    const completed = trades.filter((t: any) => t.status === "complete" && t.combined_cost != null);
    if (!completed.length) {
      return (
        <Card>
          <CardHeader className="pb-1">
            <CardTitle className="text-sm text-muted-foreground">{title}</CardTitle>
          </CardHeader>
          <CardContent className="h-56 flex items-center justify-center text-muted-foreground text-sm">
            No completed arbs yet
          </CardContent>
        </Card>
      );
    }

    const prices = completed.map((t: any) => t.combined_cost as number);
    const minP = Math.floor(Math.min(...prices) * 100) / 100;
    const maxP = Math.ceil(Math.max(...prices) * 100) / 100;

    const bins: { label: string; min: number; max: number; count: number; profitable: boolean }[] = [];
    for (let p = minP; p < maxP + 0.001; p = Number((p + 0.01).toFixed(2))) {
      const upper = Number((p + 0.01).toFixed(2));
      const count = prices.filter((x: number) => x >= p && x < upper).length;
      bins.push({
        label: p.toFixed(2),
        min: p,
        max: upper,
        count,
        // Breakeven with $0.08 fees on $4 notional: ~0.978 for equal splits
        profitable: p < 0.978,
      });
    }

    return (
      <Card>
        <CardHeader className="pb-1">
          <div className="flex items-center justify-between">
            <CardTitle className="text-sm text-muted-foreground">{title}</CardTitle>
            <span className="text-[10px] text-muted-foreground">breakeven ≈ 0.978</span>
          </div>
        </CardHeader>
        <CardContent className="h-56">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={bins} margin={{ top: 5, right: 10, bottom: 5, left: 10 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
              <XAxis dataKey="label" tick={{ fill: "hsl(var(--muted-foreground))", fontSize: 9 }} tickLine={false} axisLine={false} />
              <YAxis tick={{ fill: "hsl(var(--muted-foreground))", fontSize: 9 }} tickLine={false} axisLine={false} />
              <Tooltip
                contentStyle={{ background: "hsl(var(--card))", border: "1px solid hsl(var(--border))", borderRadius: 8, fontSize: 12 }}
                formatter={(value: any, _: any, props: any) => [
                  `${value} arbs (${props.payload?.profitable ? "✓ profitable" : "✗ near breakeven"})`,
                  "Count",
                ]}
              />
              <Bar dataKey="count" radius={[3, 3, 0, 0]}>
                {bins.map((b, i) => (
                  <Cell key={i} fill={b.profitable ? "#34d399" : "#f59e0b"} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </CardContent>
      </Card>
    );
  }

  // Paper mode: original Entry Price Distribution
  const prices = trades.map((t: any) => t.entry_price).filter(Boolean);
  if (!prices.length) {
    return (
      <Card>
        <CardHeader className="pb-1">
          <CardTitle className="text-sm text-muted-foreground">{title}</CardTitle>
        </CardHeader>
        <CardContent className="h-56 flex items-center justify-center text-muted-foreground text-sm">
          No entry prices found
        </CardContent>
      </Card>
    );
  }

  const minP = Math.floor(Math.min(...prices) * 100) / 100;
  const maxP = Math.ceil(Math.max(...prices) * 100) / 100;

  const bins: { label: string; count: number; goodPayoff: boolean }[] = [];
  for (let p = minP; p < maxP; p = Number((p + 0.01).toFixed(2))) {
    const upper = Number((p + 0.01).toFixed(2));
    const count = prices.filter((x: number) => x >= p && x < upper).length;
    bins.push({ label: p.toFixed(2), count, goodPayoff: p < 0.52 });
  }

  return (
    <Card>
      <CardHeader className="pb-1">
        <CardTitle className="text-sm text-muted-foreground">{title}</CardTitle>
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
