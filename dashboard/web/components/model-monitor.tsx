"use client";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useTrades } from "@/hooks/use-trades";

export function ModelMonitor() {
  const { data } = useTrades(10);
  if (!data?.trades?.length) return null;

  const last = data.trades[data.trades.length - 1];

  return (
    <Card className="bg-zinc-900 border-zinc-800">
      <CardHeader className="pb-2">
        <CardTitle className="text-sm text-zinc-400">Last Prediction</CardTitle>
      </CardHeader>
      <CardContent className="text-xs font-mono space-y-1">
        <div className="flex justify-between">
          <span className="text-zinc-500">Raw prob</span>
          <span>{last.raw_prob?.toFixed(4) || "\u2014"}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-zinc-500">Cal prob</span>
          <span>{last.prob?.toFixed(4) || "\u2014"}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-zinc-500">Confidence</span>
          <span>{(last.confidence * 100).toFixed(1)}%</span>
        </div>
        <div className="flex justify-between">
          <span className="text-zinc-500">Edge</span>
          <span className={last.edge > 0 ? "text-emerald-400" : "text-red-400"}>
            {(last.edge * 100).toFixed(1)}%
          </span>
        </div>
        <div className="flex justify-between">
          <span className="text-zinc-500">Entry</span>
          <span>${last.entry_price?.toFixed(2)}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-zinc-500">Source</span>
          <span className="text-amber-400">{last.price_source || "\u2014"}</span>
        </div>
      </CardContent>
    </Card>
  );
}
