"use client";
import { useState } from "react";
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

function StatusBadge({ status }: { status: string }) {
  if (status === "complete" || status === "win")
    return <span className="text-emerald-400 font-bold">WIN</span>;
  if (status === "lose")
    return <span className="text-red-400 font-bold">LOSE</span>;
  if (status === "abandoned")
    return <span className="text-amber-400 font-bold">ABD</span>;
  return <span className="text-muted-foreground">{status}</span>;
}

function SideBadge({ side }: { side: string }) {
  return (
    <Badge
      variant="outline"
      className={side === "UP"
        ? "border-emerald-800 bg-emerald-900/50 text-emerald-300"
        : "border-red-800 bg-red-900/50 text-red-300"}
    >
      {side}
    </Badge>
  );
}

function TradeDetail({ t }: { t: any }) {
  const isArb = !!t.leg2_side;
  const hasContext = t.entry_confidence != null;
  const remainMins = t.window_remain_at_entry != null
    ? `${Math.floor(t.window_remain_at_entry / 60)}m${t.window_remain_at_entry % 60}s remaining`
    : null;

  return (
    <div className="grid grid-cols-2 gap-x-8 gap-y-1 text-xs px-2 py-2 text-muted-foreground">
      {/* Left column: entry context */}
      <div className="space-y-1">
        <div className="font-semibold text-foreground/70 mb-1">Entry signal</div>
        {hasContext ? (
          <>
            <div>Confidence: <span className="font-mono text-foreground">{t.entry_confidence?.toFixed(1)}</span></div>
            <div>Direction: <span className={`font-mono font-semibold ${t.entry_direction === "UP" ? "text-emerald-400" : "text-red-400"}`}>{t.entry_direction}</span></div>
            <div>TFI: <span className="font-mono text-foreground">{t.entry_tfi != null ? (t.entry_tfi > 0 ? "+" : "") + t.entry_tfi.toFixed(1) : "—"}</span></div>
            <div>OBI: <span className="font-mono text-foreground">{t.entry_obi != null ? (t.entry_obi > 0 ? "+" : "") + t.entry_obi.toFixed(3) : "—"}</span></div>
            {remainMins && <div>At: <span className="font-mono text-foreground">{remainMins}</span></div>}
          </>
        ) : (
          <div className="italic text-xs">No signal data (old format)</div>
        )}
      </div>

      {/* Right column: outcome context */}
      <div className="space-y-1">
        <div className="font-semibold text-foreground/70 mb-1">Outcome</div>
        {isArb ? (
          <>
            <div>Type: <span className="font-mono text-emerald-400">Instant arb</span></div>
            <div>Combined: <span className="font-mono text-foreground">${(t.leg1_price + t.leg2_price).toFixed(3)}</span></div>
            <div>Leg1: {t.leg1_side} @ ${t.leg1_price?.toFixed(3)}</div>
            <div>Leg2: {t.leg2_side} @ ${t.leg2_price?.toFixed(3)}</div>
          </>
        ) : (
          <>
            <div>Type: <span className="font-mono text-blue-400">Directional</span></div>
            <div>Entry: <span className="font-mono text-foreground">${t.entry_price?.toFixed(3)}</span></div>
            <div>Exit: <span className="font-mono text-foreground">{t.exit_price ? `$${t.exit_price.toFixed(3)}` : "—"}</span></div>
            {t.status === "abandoned" && t.abandon_reason && (
              <div>Reason: <span className="font-mono text-amber-400">{t.abandon_reason}</span></div>
            )}
            {t.status === "win" && (
              <div className="text-emerald-400">✓ Resolved as WIN</div>
            )}
            {t.status === "lose" && (
              <div className="text-red-400">✗ Resolved as LOSE</div>
            )}
          </>
        )}
      </div>
    </div>
  );
}

function ArbTradesTable({ trades }: { trades: any[] }) {
  const [expanded, setExpanded] = useState<number | null>(null);
  const sorted = trades.slice().reverse();

  // Detect new format (has "side" field) vs legacy (has "leg1_side")
  const isNewFormat = sorted.length > 0 && "side" in sorted[0];

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead className="w-6"></TableHead>
          <TableHead>Time</TableHead>
          <TableHead>Side</TableHead>
          <TableHead className="text-right">Entry</TableHead>
          <TableHead className="text-right">Exit</TableHead>
          <TableHead className="text-right">Profit</TableHead>
          <TableHead className="text-right">Capital</TableHead>
          <TableHead className="text-center">Status</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {sorted.map((t: any, i: number) => {
          const side = t.side ?? t.leg1_side ?? "?";
          const entryPrice = t.entry_price ?? t.leg1_price;
          const exitPrice = t.exit_price ?? t.leg2_price;
          const isOpen = expanded === i;

          return (
            <>
              <TableRow
                key={i}
                className="cursor-pointer hover:bg-muted/30"
                onClick={() => setExpanded(isOpen ? null : i)}
              >
                <TableCell className="text-muted-foreground text-xs pr-0">
                  {isOpen ? "▾" : "▸"}
                </TableCell>
                <TableCell className="text-muted-foreground">{formatTime(t.timestamp)}</TableCell>
                <TableCell><SideBadge side={side} /></TableCell>
                <TableCell className="text-right font-mono">
                  {entryPrice != null ? `$${entryPrice.toFixed(3)}` : "\u2014"}
                </TableCell>
                <TableCell className="text-right font-mono">
                  {exitPrice != null ? `$${exitPrice.toFixed(3)}` : "\u2014"}
                </TableCell>
                <TableCell className={`text-right font-mono ${(t.profit ?? 0) >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                  {formatUsd(t.profit ?? 0, 4)}
                </TableCell>
                <TableCell className="text-right font-mono">
                  ${t.capital_after?.toFixed(2) ?? "\u2014"}
                </TableCell>
                <TableCell className="text-center">
                  <StatusBadge status={t.status} />
                </TableCell>
              </TableRow>
              {isOpen && (
                <TableRow key={`${i}-detail`} className="bg-muted/10 hover:bg-muted/10">
                  <TableCell colSpan={8} className="p-0">
                    <TradeDetail t={t} />
                  </TableCell>
                </TableRow>
              )}
            </>
          );
        })}
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

  const isArb = "status" in (data.trades[0] || {});

  if (isArb) {
    return <ArbTradesTable trades={data.trades} />;
  }
  return <PaperTradesTable trades={data.trades} />;
}
