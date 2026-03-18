"use client";
import { useStats } from "@/hooks/use-trades";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer,
  ReferenceLine, CartesianGrid
} from "recharts";

export function PnlChart() {
  const { data } = useStats();
  if (!data?.capital_curve?.length) {
    return (
      <Card className="bg-zinc-900/80 border-zinc-800">
        <CardHeader><CardTitle className="text-sm text-zinc-400">Capital Curve</CardTitle></CardHeader>
        <CardContent className="h-72 flex items-center justify-center text-zinc-600 text-sm">
          No trades yet
        </CardContent>
      </Card>
    );
  }

  const initial = data.initial_capital || 100;
  const chartData = data.capital_curve.map((p: any, i: number) => ({
    idx: i + 1,
    capital: Number(p.capital.toFixed(2)),
    pnl: Number((p.capital - initial).toFixed(2)),
    ts: p.ts
      ? new Date(p.ts).toLocaleTimeString("en-US", { hour12: false, hour: "2-digit", minute: "2-digit" })
      : "",
  }));

  const current = chartData[chartData.length - 1]?.capital ?? initial;
  const isUp = current >= initial;
  const minCap = Math.min(...chartData.map((d: any) => d.capital));
  const maxCap = Math.max(...chartData.map((d: any) => d.capital));

  return (
    <Card className="bg-zinc-900/80 border-zinc-800">
      <CardHeader className="pb-1">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm text-zinc-400">Capital Curve</CardTitle>
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
            <CartesianGrid strokeDasharray="3 3" stroke="#27272a" />
            <XAxis dataKey="ts" tick={{ fill: "#52525b", fontSize: 9 }} tickLine={false} axisLine={false} />
            <YAxis
              domain={[Math.floor(minCap - 1), Math.ceil(maxCap + 1)]}
              tick={{ fill: "#52525b", fontSize: 9 }}
              tickLine={false} axisLine={false}
              tickFormatter={(v: number) => `$${v}`}
            />
            <Tooltip
              contentStyle={{ background: "#18181b", border: "1px solid #3f3f46", borderRadius: 8, fontSize: 12 }}
              labelStyle={{ color: "#71717a" }}
              formatter={(value: any) => [`$${Number(value).toFixed(2)}`, "Capital"]}
            />
            <ReferenceLine y={initial} stroke="#52525b" strokeDasharray="4 4" />
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
