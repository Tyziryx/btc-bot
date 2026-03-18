import { StatsCards } from "@/components/stats-cards";
import { PnlChart } from "@/components/pnl-chart";
import { TradesTable } from "@/components/trades-table";
import { LiveLogs } from "@/components/live-logs";
import { ModelMonitor } from "@/components/model-monitor";
import { HourlyHeatmap } from "@/components/hourly-heatmap";
import { TradeAnalysis } from "@/components/trade-analysis";

export default function Dashboard() {
  return (
    <div className="max-w-[1400px] mx-auto px-4 py-6 space-y-5">
      {/* Header */}
      <div className="border-b border-zinc-800 pb-4">
        <h1 className="text-2xl font-bold tracking-tight">BTC Bot Dashboard</h1>
        <p className="text-xs text-zinc-500 mt-0.5">Polymarket 15min Paper Trader V2 Pro — 41 features, minute 0 early entry</p>
      </div>

      {/* Stats row */}
      <StatsCards />

      {/* Capital curve full width */}
      <PnlChart />

      {/* Analysis row */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="lg:col-span-2">
          <TradeAnalysis />
        </div>
        <div className="space-y-4">
          <ModelMonitor />
          <HourlyHeatmap />
        </div>
      </div>

      {/* Trades + Logs */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div>
          <h2 className="text-xs text-zinc-500 uppercase tracking-widest mb-2 font-medium">Recent Trades</h2>
          <TradesTable />
        </div>
        <div>
          <h2 className="text-xs text-zinc-500 uppercase tracking-widest mb-2 font-medium">Live Logs</h2>
          <LiveLogs />
        </div>
      </div>
    </div>
  );
}
