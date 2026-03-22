"use client";
import { useTrades } from "@/hooks/use-trades";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table, TableHeader, TableHead, TableBody, TableRow, TableCell,
} from "@/components/ui/table";

function formatTime(iso: string): string {
  if (!iso) return "\u2014";
  return new Date(iso).toLocaleTimeString("en-US", { hour12: false });
}

function formatUsd(n: number): string {
  const sign = n >= 0 ? "+" : "";
  return `${sign}$${Math.abs(n).toFixed(2)}`;
}

export function TradesTable() {
  const { data } = useTrades(30);

  if (!data) {
    return (
      <div className="space-y-2">
        {Array.from({ length: 5 }).map((_, i) => (
          <Skeleton key={i} className="h-8 w-full" />
        ))}
      </div>
    );
  }

  if (!data.trades?.length) {
    return <p className="text-muted-foreground text-sm">No trades yet</p>;
  }

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Time</TableHead>
          <TableHead>Dir</TableHead>
          <TableHead className="text-right">Entry</TableHead>
          <TableHead className="text-right">Edge</TableHead>
          <TableHead>Source</TableHead>
          <TableHead className="text-right">Bet</TableHead>
          <TableHead className="text-right">PnL</TableHead>
          <TableHead className="text-right">Capital</TableHead>
          <TableHead className="text-center">Result</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {data.trades.slice().reverse().map((t: any, i: number) => (
          <TableRow key={i}>
            <TableCell className="text-muted-foreground">{formatTime(t.timestamp)}</TableCell>
            <TableCell>
              <Badge
                variant="outline"
                className={t.direction === "UP" ? "border-emerald-800 bg-emerald-900/50 text-emerald-300" : "border-red-800 bg-red-900/50 text-red-300"}
              >
                {t.direction}
              </Badge>
            </TableCell>
            <TableCell className="text-right font-mono">${t.entry_price?.toFixed(2) ?? "\u2014"}</TableCell>
            <TableCell className="text-right font-mono">{t.edge != null ? `${(t.edge * 100).toFixed(1)}%` : "\u2014"}</TableCell>
            <TableCell className="text-muted-foreground text-xs">{t.price_source ?? "\u2014"}</TableCell>
            <TableCell className="text-right font-mono">${t.bet_size?.toFixed(2) ?? "\u2014"}</TableCell>
            <TableCell className={`text-right font-mono ${t.pnl >= 0 ? "text-emerald-400" : "text-red-400"}`}>
              {formatUsd(t.pnl)}
            </TableCell>
            <TableCell className="text-right font-mono">${t.capital_after?.toFixed(2) ?? "\u2014"}</TableCell>
            <TableCell className="text-center">
              {t.won === null || t.actual === "DRAW"
                ? <span className="text-yellow-400 font-bold">D</span>
                : t.won
                  ? <span className="text-emerald-400 font-bold">W</span>
                  : <span className="text-red-400 font-bold">L</span>}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
