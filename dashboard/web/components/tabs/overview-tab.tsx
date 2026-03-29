// dashboard/web/components/tabs/overview-tab.tsx
"use client";
import { StatsCards } from "@/components/stats-cards";
import { CapitalChart } from "@/components/capital-chart";
import { useStats } from "@/hooks/use-trades";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

function ConfBucketBar({
  label,
  data,
}: {
  label: string;
  data: { win_rate: number; total: number; wins: number };
}) {
  const wr = data.win_rate;
  const color = wr >= 65 ? "bg-emerald-400" : wr >= 50 ? "bg-amber-400" : "bg-red-400";
  return (
    <div className="space-y-1">
      <div className="flex justify-between font-mono text-[10px]">
        <span className="text-muted-foreground">{label}</span>
        <span className={wr >= 65 ? "text-emerald-400" : wr >= 50 ? "text-amber-400" : "text-red-400"}>
          {wr.toFixed(0)}% <span className="text-muted-foreground">({data.wins}/{data.total})</span>
        </span>
      </div>
      <div className="h-1.5 bg-muted rounded-full overflow-hidden">
        <div className={`h-full ${color} rounded-full`} style={{ width: `${wr}%` }} />
      </div>
    </div>
  );
}

function QuantMetrics() {
  const { data } = useStats();
  if (!data) return null;

  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
      {[
        { label: "Sharpe", value: data.sharpe ?? 0, good: (v: number) => v >= 1.0, fmt: (v: number) => v.toFixed(2) },
        { label: "Sortino", value: data.sortino ?? 0, good: (v: number) => v >= 1.5, fmt: (v: number) => v.toFixed(2) },
        { label: "Calmar", value: data.calmar ?? 0, good: (v: number) => v >= 0.5, fmt: (v: number) => v.toFixed(2) },
        { label: "Max DD (trades)", value: data.max_dd_trades ?? 0, good: (v: number) => v <= 3, fmt: (v: number) => String(v) },
      ].map(({ label, value, good, fmt }) => (
        <Card key={label}>
          <CardContent className="pt-4 pb-3 px-4">
            <p className="text-[10px] font-mono text-muted-foreground uppercase tracking-widest mb-1">{label}</p>
            <p className={`text-xl font-bold font-mono tabular-nums ${good(value) ? "text-emerald-400" : "text-amber-400"}`}>
              {fmt(value)}
            </p>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

function WinByConfidence() {
  const { data } = useStats();
  if (!data?.win_by_conf) return null;

  const wbc = data.win_by_conf as Record<string, { win_rate: number; total: number; wins: number }>;
  const hasAny = Object.values(wbc).some((b) => b.total > 0);
  if (!hasAny) return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-[10px] font-mono text-muted-foreground uppercase tracking-widest">
          Win Rate by Confidence
        </CardTitle>
      </CardHeader>
      <CardContent>
        <p className="text-xs text-muted-foreground font-mono">Waiting for trades…</p>
      </CardContent>
    </Card>
  );

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-[10px] font-mono text-muted-foreground uppercase tracking-widest">
          Win Rate by Confidence Bucket
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <ConfBucketBar label="65 – 70" data={wbc["65_70"]} />
        <ConfBucketBar label="70 – 80" data={wbc["70_80"]} />
        <ConfBucketBar label="80 +"    data={wbc["80_plus"]} />
        <p className="text-[9px] text-muted-foreground font-mono pt-1">
          Directional trades only — instant arbs excluded
        </p>
      </CardContent>
    </Card>
  );
}

export function OverviewTab() {
  return (
    <div className="space-y-5 pb-10">
      <StatsCards />
      <CapitalChart />
      <QuantMetrics />
      <WinByConfidence />
    </div>
  );
}
