"use client";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { OverviewTab } from "@/components/tabs/overview-tab";
import { TradesTab } from "@/components/tabs/trades-tab";
import { SignalTab } from "@/components/tabs/signal-tab";
import { LogsTab } from "@/components/tabs/logs-tab";
import { useStats } from "@/hooks/use-trades";

function LiveDot() {
  return (
    <span className="inline-flex items-center gap-1.5 font-mono text-[10px] text-emerald-400">
      <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
      LIVE
    </span>
  );
}

export default function Dashboard() {
  const { data } = useStats();
  const capital = data?.capital?.toFixed(2) ?? "—";
  const roi = data ? (data.roi >= 0 ? "+" : "") + data.roi.toFixed(2) + "%" : "—";
  const isUp = data ? data.capital >= data.initial_capital : true;

  return (
    <div className="min-h-screen bg-background">
      {/* ── Top bar ─────────────────────────────────────────────────────── */}
      <header className="border-b border-border px-6 py-3 flex items-center justify-between">
        <div>
          <h1 className="text-xs font-mono font-bold tracking-[0.2em] text-primary">
            ▸ ARB BOT PRO
          </h1>
          <p className="text-[10px] text-muted-foreground font-mono mt-0.5">
            Polymarket BTC 15min · {new Date().toLocaleDateString("fr-FR")}
          </p>
        </div>
        <div className="flex items-center gap-6 font-mono text-xs">
          <span className={isUp ? "text-emerald-400 font-bold" : "text-red-400 font-bold"}>
            ${capital}
          </span>
          <span className={isUp ? "text-emerald-400" : "text-red-400"}>{roi}</span>
          <LiveDot />
        </div>
      </header>

      {/* ── Tabs ─────────────────────────────────────────────────────────── */}
      <Tabs defaultValue="overview" className="px-6 pt-4">
        <TabsList className="mb-5 bg-card border border-border font-mono text-[11px] gap-0 p-0.5 rounded-sm">
          <TabsTrigger
            value="overview"
            className="rounded-sm px-5 py-1.5 data-[state=active]:bg-primary data-[state=active]:text-primary-foreground"
          >
            📊 Overview
          </TabsTrigger>
          <TabsTrigger
            value="trades"
            className="rounded-sm px-5 py-1.5 data-[state=active]:bg-primary data-[state=active]:text-primary-foreground"
          >
            📋 Trades
          </TabsTrigger>
          <TabsTrigger
            value="signal"
            className="rounded-sm px-5 py-1.5 data-[state=active]:bg-primary data-[state=active]:text-primary-foreground"
          >
            ⚡ Signal
          </TabsTrigger>
          <TabsTrigger
            value="logs"
            className="rounded-sm px-5 py-1.5 data-[state=active]:bg-primary data-[state=active]:text-primary-foreground"
          >
            🗒 Logs
          </TabsTrigger>
        </TabsList>

        <TabsContent value="overview"><OverviewTab /></TabsContent>
        <TabsContent value="trades"><TradesTab /></TabsContent>
        <TabsContent value="signal"><SignalTab /></TabsContent>
        <TabsContent value="logs"><LogsTab /></TabsContent>
      </Tabs>
    </div>
  );
}
