import { StatsCards } from "@/components/stats-cards";
import { PnlChart } from "@/components/pnl-chart";
import { WinRateChart } from "@/components/win-rate-chart";
import { EdgeScatter } from "@/components/edge-scatter";
import { DirectionPnl } from "@/components/direction-pnl";
import { EntryDistribution } from "@/components/entry-distribution";
import { TradesTable } from "@/components/trades-table";
import { FeatureMonitor } from "@/components/feature-monitor";
import { LiveLogs } from "@/components/live-logs";
import { Separator } from "@/components/ui/separator";

export default function Dashboard() {
  return (
    <div className="max-w-[1400px] mx-auto px-4 py-6 space-y-5">
      {/* Header */}
      <div className="border-b border-border pb-4">
        <h1 className="text-2xl font-bold tracking-tight">BTC Bot Dashboard</h1>
        <p className="text-xs text-muted-foreground mt-0.5">
          Polymarket 15min Paper Trader V2 Pro — 41 features, minute 0 early entry
        </p>
      </div>

      {/* Row 1: Stats */}
      <StatsCards />

      {/* Row 2: Capital curve */}
      <PnlChart />

      {/* Row 3: Win Rate Rolling + Edge vs PnL */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <WinRateChart />
        <EdgeScatter />
      </div>

      {/* Row 4: Direction PnL + Entry Distribution */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <DirectionPnl />
        <EntryDistribution />
      </div>

      <Separator />

      {/* Row 5: Trades + Feature Monitor */}
      <div className="grid grid-cols-1 lg:grid-cols-4 gap-4">
        <div className="lg:col-span-3">
          <h2 className="text-xs text-muted-foreground uppercase tracking-widest mb-2 font-medium">Recent Trades</h2>
          <TradesTable />
        </div>
        <div>
          <FeatureMonitor />
        </div>
      </div>

      <Separator />

      {/* Row 6: Live Logs */}
      <div>
        <h2 className="text-xs text-muted-foreground uppercase tracking-widest mb-2 font-medium">Live Logs</h2>
        <LiveLogs />
      </div>
    </div>
  );
}
