"use client";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useTrades } from "@/hooks/use-trades";
import {
  ScatterChart, Scatter, XAxis, YAxis, Tooltip, ResponsiveContainer,
  CartesianGrid, ReferenceLine, Cell,
} from "recharts";

export function EdgeScatter() {
  const { data } = useTrades(200);

  if (!data) {
    return (
      <Card>
        <CardHeader className="pb-1">
          <CardTitle className="text-sm text-muted-foreground">Edge vs PnL</CardTitle>
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
          <CardTitle className="text-sm text-muted-foreground">Edge vs PnL</CardTitle>
        </CardHeader>
        <CardContent className="h-56 flex items-center justify-center text-muted-foreground text-sm">
          No trades yet
        </CardContent>
      </Card>
    );
  }

  const scatterData = trades.map((t: any) => ({
    edge: Number((t.edge * 100).toFixed(1)),
    pnl: Number(t.pnl.toFixed(2)),
    won: t.won,
  }));

  return (
    <Card>
      <CardHeader className="pb-1">
        <CardTitle className="text-sm text-muted-foreground">Edge vs PnL</CardTitle>
      </CardHeader>
      <CardContent className="h-56">
        <ResponsiveContainer width="100%" height="100%">
          <ScatterChart margin={{ top: 5, right: 10, bottom: 5, left: 10 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
            <XAxis
              dataKey="edge" type="number" name="Edge"
              tick={{ fill: "hsl(var(--muted-foreground))", fontSize: 9 }}
              tickLine={false} axisLine={false}
              tickFormatter={(v: number) => `${v}%`}
              label={{ value: "Edge %", position: "bottom", fill: "hsl(var(--muted-foreground))", fontSize: 10 }}
            />
            <YAxis
              dataKey="pnl" type="number" name="PnL"
              tick={{ fill: "hsl(var(--muted-foreground))", fontSize: 9 }}
              tickLine={false} axisLine={false}
              tickFormatter={(v: number) => `$${v}`}
            />
            <Tooltip
              contentStyle={{ background: "hsl(var(--card))", border: "1px solid hsl(var(--border))", borderRadius: 8, fontSize: 12 }}
              formatter={(value: any, name: any) => [name === "Edge" ? `${value}%` : `$${value}`, name]}
            />
            <ReferenceLine y={0} stroke="hsl(var(--muted-foreground))" strokeDasharray="4 4" />
            <Scatter data={scatterData}>
              {scatterData.map((entry: any, i: number) => (
                <Cell key={i} fill={entry.won ? "#34d399" : "#f87171"} />
              ))}
            </Scatter>
          </ScatterChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  );
}
