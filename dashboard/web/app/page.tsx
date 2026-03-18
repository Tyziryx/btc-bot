import { StatsCards } from "@/components/stats-cards";
import { PnlChart } from "@/components/pnl-chart";
import { TradesTable } from "@/components/trades-table";
import { LiveLogs } from "@/components/live-logs";
import { BotControls } from "@/components/bot-controls";
import { ModelMonitor } from "@/components/model-monitor";

export default function Dashboard() {
  return (
    <div className="max-w-7xl mx-auto px-4 py-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">BTC Bot Dashboard</h1>
          <p className="text-sm text-zinc-500">Polymarket 15min Paper Trader V2 Pro</p>
        </div>
      </div>

      {/* Stats row */}
      <StatsCards />

      {/* Charts + Controls */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="lg:col-span-2">
          <PnlChart />
        </div>
        <div className="space-y-4">
          <BotControls />
          <ModelMonitor />
        </div>
      </div>

      {/* Trades + Logs */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div>
          <h2 className="text-sm text-zinc-400 mb-2 font-semibold">Recent Trades</h2>
          <TradesTable />
        </div>
        <div>
          <h2 className="text-sm text-zinc-400 mb-2 font-semibold">Live Logs</h2>
          <LiveLogs />
        </div>
      </div>
    </div>
  );
}
