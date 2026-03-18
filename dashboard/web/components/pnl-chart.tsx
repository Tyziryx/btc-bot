"use client";
import { useStats } from "@/hooks/use-trades";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer } from "recharts";

export function PnlChart() {
  const { data } = useStats();
  if (!data?.capital_curve?.length) return null;

  const chartData = data.capital_curve.map((p: any, i: number) => ({
    idx: i + 1,
    capital: p.capital,
    ts: p.ts ? new Date(p.ts).toLocaleTimeString("en-US", { hour12: false, hour: "2-digit", minute: "2-digit" }) : "",
  }));

  const initial = data.initial_capital || 100;
  const isUp = chartData[chartData.length - 1]?.capital >= initial;

  return (
    <Card className="bg-zinc-900 border-zinc-800">
      <CardHeader className="pb-2">
        <CardTitle className="text-sm text-zinc-400">Capital Curve</CardTitle>
      </CardHeader>
      <CardContent className="h-64">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={chartData}>
            <defs>
              <linearGradient id="grad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor={isUp ? "#34d399" : "#f87171"} stopOpacity={0.3} />
                <stop offset="95%" stopColor={isUp ? "#34d399" : "#f87171"} stopOpacity={0} />
              </linearGradient>
            </defs>
            <XAxis dataKey="ts" tick={{ fill: "#71717a", fontSize: 10 }} />
            <YAxis domain={["auto", "auto"]} tick={{ fill: "#71717a", fontSize: 10 }} />
            <Tooltip
              contentStyle={{ background: "#18181b", border: "1px solid #3f3f46", borderRadius: 8 }}
              labelStyle={{ color: "#a1a1aa" }}
            />
            <Area
              type="monotone" dataKey="capital" stroke={isUp ? "#34d399" : "#f87171"}
              fill="url(#grad)" strokeWidth={2}
            />
          </AreaChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  );
}
