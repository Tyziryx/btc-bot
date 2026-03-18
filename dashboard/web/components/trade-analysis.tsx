"use client";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useTrades } from "@/hooks/use-trades";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from "recharts";

export function TradeAnalysis() {
  const { data } = useTrades(200);
  if (!data?.trades?.length) return null;

  const trades = data.trades;

  // Direction stats
  const upTrades = trades.filter((t: any) => t.direction === "UP");
  const downTrades = trades.filter((t: any) => t.direction === "DOWN");
  const upWR = upTrades.length > 0 ? (upTrades.filter((t: any) => t.won).length / upTrades.length * 100) : 0;
  const downWR = downTrades.length > 0 ? (downTrades.filter((t: any) => t.won).length / downTrades.length * 100) : 0;

  // Edge distribution
  const edgeBuckets = [
    { range: "3-5%", min: 0.03, max: 0.05 },
    { range: "5-8%", min: 0.05, max: 0.08 },
    { range: "8-12%", min: 0.08, max: 0.12 },
    { range: "12%+", min: 0.12, max: 1 },
  ];

  const edgeData = edgeBuckets.map((b) => {
    const bucket = trades.filter((t: any) => t.edge >= b.min && t.edge < b.max);
    const wins = bucket.filter((t: any) => t.won).length;
    return {
      range: b.range,
      trades: bucket.length,
      wr: bucket.length > 0 ? (wins / bucket.length * 100) : 0,
      pnl: bucket.reduce((sum: number, t: any) => sum + (t.pnl || 0), 0),
    };
  });

  // Streak analysis
  let maxWinStreak = 0, maxLossStreak = 0, cur = 0, curType = true;
  for (const t of trades) {
    if (t.won === curType) {
      cur++;
    } else {
      if (curType && cur > maxWinStreak) maxWinStreak = cur;
      if (!curType && cur > maxLossStreak) maxLossStreak = cur;
      curType = t.won;
      cur = 1;
    }
  }
  if (curType && cur > maxWinStreak) maxWinStreak = cur;
  if (!curType && cur > maxLossStreak) maxLossStreak = cur;

  // Recent form (last 10)
  const recent = trades.slice(-10);
  const recentWR = recent.filter((t: any) => t.won).length / recent.length * 100;

  // PnL per trade bar chart
  const pnlBars = trades.slice(-30).map((t: any, i: number) => ({
    idx: i,
    pnl: t.pnl,
    won: t.won,
  }));

  return (
    <div className="space-y-4">
      {/* Direction + Streaks */}
      <Card className="bg-zinc-900/80 border-zinc-800">
        <CardHeader className="pb-2">
          <CardTitle className="text-sm text-zinc-400">Trade Analysis</CardTitle>
        </CardHeader>
        <CardContent className="grid grid-cols-2 md:grid-cols-4 gap-4 text-xs">
          <div>
            <p className="text-zinc-500 mb-1">UP trades</p>
            <p className="text-lg font-bold text-emerald-400">{upWR.toFixed(0)}%</p>
            <p className="text-zinc-600">{upTrades.length} trades</p>
          </div>
          <div>
            <p className="text-zinc-500 mb-1">DOWN trades</p>
            <p className="text-lg font-bold text-red-400">{downWR.toFixed(0)}%</p>
            <p className="text-zinc-600">{downTrades.length} trades</p>
          </div>
          <div>
            <p className="text-zinc-500 mb-1">Best/Worst streak</p>
            <p className="tabular-nums">
              <span className="text-emerald-400 font-bold">{maxWinStreak}W</span>
              {" / "}
              <span className="text-red-400 font-bold">{maxLossStreak}L</span>
            </p>
          </div>
          <div>
            <p className="text-zinc-500 mb-1">Last 10 form</p>
            <p className={`text-lg font-bold ${recentWR >= 55 ? "text-emerald-400" : recentWR >= 50 ? "text-amber-400" : "text-red-400"}`}>
              {recentWR.toFixed(0)}%
            </p>
            <div className="flex gap-0.5 mt-1">
              {recent.map((t: any, i: number) => (
                <div key={i} className={`w-2 h-2 rounded-full ${t.won ? "bg-emerald-400" : "bg-red-400"}`} />
              ))}
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Edge breakdown */}
      <Card className="bg-zinc-900/80 border-zinc-800">
        <CardHeader className="pb-2">
          <CardTitle className="text-sm text-zinc-400">Edge Performance</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-4 gap-2 text-xs text-center">
            {edgeData.map((b) => (
              <div key={b.range} className="bg-zinc-800/50 rounded p-2">
                <p className="text-zinc-500 text-[10px]">{b.range}</p>
                <p className={`font-bold ${b.wr >= 55 ? "text-emerald-400" : b.wr >= 50 ? "text-amber-400" : "text-red-400"}`}>
                  {b.wr.toFixed(0)}%
                </p>
                <p className="text-zinc-600">{b.trades}t</p>
                <p className={`tabular-nums ${b.pnl >= 0 ? "text-emerald-500" : "text-red-500"}`}>
                  {b.pnl >= 0 ? "+" : ""}${b.pnl.toFixed(2)}
                </p>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* PnL per trade */}
      <Card className="bg-zinc-900/80 border-zinc-800">
        <CardHeader className="pb-1">
          <CardTitle className="text-sm text-zinc-400">PnL per Trade (last 30)</CardTitle>
        </CardHeader>
        <CardContent className="h-32">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={pnlBars} margin={{ top: 5, right: 5, bottom: 5, left: 5 }}>
              <Tooltip
                contentStyle={{ background: "#18181b", border: "1px solid #3f3f46", borderRadius: 8, fontSize: 11 }}
                formatter={(value: any) => [`$${Number(value).toFixed(2)}`, "PnL"]}
              />
              <Bar dataKey="pnl" radius={[2, 2, 0, 0]}>
                {pnlBars.map((entry: any, i: number) => (
                  <Cell key={i} fill={entry.won ? "#34d399" : "#f87171"} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </CardContent>
      </Card>
    </div>
  );
}
