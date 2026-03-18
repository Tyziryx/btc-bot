"use client";
import { useTrades } from "@/hooks/use-trades";
import { Badge } from "@/components/ui/badge";

function formatTime(iso: string): string {
  if (!iso) return "\u2014";
  return new Date(iso).toLocaleTimeString("en-US", { hour12: false });
}

function formatUsd(n: number): string {
  const sign = n >= 0 ? "+" : "";
  return `${sign}$${Math.abs(n).toFixed(2)}`;
}

export function TradesTable() {
  const { data } = useTrades(20);
  if (!data?.trades?.length) return <p className="text-zinc-500 text-sm">No trades yet</p>;

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-zinc-500 text-xs border-b border-zinc-800">
            <th className="py-2 text-left">Time</th>
            <th className="text-left">Dir</th>
            <th className="text-right">Entry</th>
            <th className="text-right">Edge</th>
            <th className="text-right">Bet</th>
            <th className="text-right">PnL</th>
            <th className="text-right">Capital</th>
            <th className="text-center">Result</th>
          </tr>
        </thead>
        <tbody>
          {data.trades.slice().reverse().map((t: any, i: number) => (
            <tr key={i} className="border-b border-zinc-800/50 hover:bg-zinc-800/30">
              <td className="py-1.5 text-zinc-400">{formatTime(t.timestamp)}</td>
              <td>
                <Badge variant={t.direction === "UP" ? "default" : "secondary"}
                  className={t.direction === "UP" ? "bg-emerald-900 text-emerald-300" : "bg-red-900 text-red-300"}>
                  {t.direction}
                </Badge>
              </td>
              <td className="text-right font-mono">${t.entry_price?.toFixed(2)}</td>
              <td className="text-right font-mono">{(t.edge * 100).toFixed(1)}%</td>
              <td className="text-right font-mono">${t.bet_size?.toFixed(2)}</td>
              <td className={`text-right font-mono ${t.pnl >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                {formatUsd(t.pnl)}
              </td>
              <td className="text-right font-mono">${t.capital_after?.toFixed(2)}</td>
              <td className="text-center">
                {t.won
                  ? <span className="text-emerald-400 font-bold">W</span>
                  : <span className="text-red-400 font-bold">L</span>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
