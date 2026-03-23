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

function formatUsd(n: number, decimals: number = 2): string {
  const sign = n >= 0 ? "+" : "";
  return `${sign}$${Math.abs(n).toFixed(decimals)}`;
}

function ArbTradesTable({ trades }: { trades: any[] }) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Time</TableHead>
          <TableHead>Leg 1</TableHead>
          <TableHead className="text-right">L1 Price</TableHead>
          <TableHead>Leg 2</TableHead>
          <TableHead className="text-right">L2 Price</TableHead>
          <TableHead className="text-right">Combined</TableHead>
          <TableHead className="text-right">Profit</TableHead>
          <TableHead className="text-right">Capital</TableHead>
          <TableHead className="text-center">Status</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {trades.slice().reverse().map((t: any, i: number) => (
          <TableRow key={i}>
            <TableCell className="text-muted-foreground">{formatTime(t.timestamp)}</TableCell>
            <TableCell>
              <Badge
                variant="outline"
                className={t.leg1_side === "UP" ? "border-emerald-800 bg-emerald-900/50 text-emerald-300" : "border-red-800 bg-red-900/50 text-red-300"}
              >
                {t.leg1_side}
              </Badge>
            </TableCell>
            <TableCell className="text-right font-mono">${t.leg1_price?.toFixed(3) ?? "\u2014"}</TableCell>
            <TableCell>
              {t.leg2_side ? (
                <Badge
                  variant="outline"
                  className={t.leg2_side === "UP" ? "border-emerald-800 bg-emerald-900/50 text-emerald-300" : "border-red-800 bg-red-900/50 text-red-300"}
                >
                  {t.leg2_side}
                </Badge>
              ) : (
                <span className="text-muted-foreground">\u2014</span>
              )}
            </TableCell>
            <TableCell className="text-right font-mono">
              {t.leg2_price != null ? `$${t.leg2_price.toFixed(3)}` : "\u2014"}
            </TableCell>
            <TableCell className="text-right font-mono">
              {t.combined_cost != null ? `$${t.combined_cost.toFixed(3)}` : "\u2014"}
            </TableCell>
            <TableCell className={`text-right font-mono ${t.profit >= 0 ? "text-emerald-400" : "text-red-400"}`}>
              {formatUsd(t.profit ?? 0, 4)}
            </TableCell>
            <TableCell className="text-right font-mono">${t.capital_after?.toFixed(2) ?? "\u2014"}</TableCell>
            <TableCell className="text-center">
              {t.status === "complete"
                ? <span className="text-emerald-400 font-bold">OK</span>
                : t.status === "abandoned"
                  ? <span className="text-amber-400 font-bold">ABD</span>
                  : <span className="text-muted-foreground">{t.status}</span>}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

function PaperTradesTable({ trades }: { trades: any[] }) {
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
        {trades.slice().reverse().map((t: any, i: number) => (
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

  // Detect mode: arb trades have "status", paper trades have "won"
  const isArb = "status" in (data.trades[0] || {});

  if (isArb) {
    return <ArbTradesTable trades={data.trades} />;
  }
  return <PaperTradesTable trades={data.trades} />;
}
