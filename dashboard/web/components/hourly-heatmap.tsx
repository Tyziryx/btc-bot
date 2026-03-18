"use client";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useStats } from "@/hooks/use-trades";

export function HourlyHeatmap() {
  const { data } = useStats();
  if (!data?.hourly || Object.keys(data.hourly).length === 0) return null;

  const hours = Array.from({ length: 24 }, (_, i) => i);

  return (
    <Card className="bg-zinc-900/80 border-zinc-800">
      <CardHeader className="pb-2">
        <CardTitle className="text-sm text-zinc-400">Win Rate by Hour (UTC)</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-12 gap-1">
          {hours.map((h) => {
            const d = data.hourly[h];
            if (!d || d.trades === 0) {
              return (
                <div key={h} className="aspect-square rounded flex flex-col items-center justify-center bg-zinc-800/50 text-[8px] text-zinc-600">
                  <span>{h}h</span>
                </div>
              );
            }
            const wr = (d.wins / d.trades) * 100;
            const bg = wr >= 60
              ? "bg-emerald-900/80 text-emerald-300"
              : wr >= 50
                ? "bg-emerald-900/40 text-emerald-400"
                : wr >= 40
                  ? "bg-red-900/40 text-red-400"
                  : "bg-red-900/80 text-red-300";

            return (
              <div key={h} className={`aspect-square rounded flex flex-col items-center justify-center ${bg} text-[9px] font-medium`}>
                <span className="text-[7px] opacity-60">{h}h</span>
                <span>{wr.toFixed(0)}%</span>
                <span className="text-[7px] opacity-50">{d.trades}t</span>
              </div>
            );
          })}
        </div>
      </CardContent>
    </Card>
  );
}
