"use client";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { useFeatures } from "@/hooks/use-features";

const ARB_LABELS: Record<string, string> = {
  ofi: "OFI",
  up_ask: "UP Ask",
  down_ask: "DOWN Ask",
  combined: "Combined",
  state: "State",
};

const PAPER_LABELS: Record<string, string> = {
  hurst: "Hurst",
  hurst_500: "Hurst",
  rv_ratio: "RV Ratio",
  poc_distance: "POC Dist",
  z_score: "Z-Score",
  mom5: "Mom 5m",
  momentum_5m: "Mom 5m",
  seas_wr: "Seas WR",
  seasonal_wr: "Seas WR",
  rsi: "RSI",
};

function arbFeatureColor(key: string, val: number | string): string {
  if (key === "ofi") {
    const n = typeof val === "number" ? val : parseFloat(val as string);
    if (Math.abs(n) >= 50) return "text-amber-400";
    return "text-muted-foreground";
  }
  if (key === "combined") {
    const n = typeof val === "number" ? val : parseFloat(val as string);
    if (n < 0.93) return "text-emerald-400";
    return "text-red-400";
  }
  if (key === "state") {
    return val === "IDLE" ? "text-muted-foreground" : "text-amber-400";
  }
  return "text-foreground";
}

function paperFeatureColor(key: string, val: number): string {
  if (key.includes("hurst")) {
    if (Math.abs(val - 0.5) < 0.01) return "text-amber-400";
    return val > 0.5 ? "text-emerald-400" : "text-red-400";
  }
  if (key === "rv_ratio") return val > 1.5 ? "text-red-400" : val > 1 ? "text-amber-400" : "text-emerald-400";
  return "text-foreground";
}

function formatValue(key: string, val: number | string): string {
  if (key === "state") return val as string;
  if (typeof val === "number") {
    if (key === "ofi") return val >= 0 ? `+${val.toFixed(1)}` : val.toFixed(1);
    return val.toFixed(3);
  }
  return String(val);
}

export function FeatureMonitor() {
  const { data } = useFeatures();

  if (!data) {
    return (
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm text-muted-foreground">Monitor</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-4 w-full" />
          ))}
        </CardContent>
      </Card>
    );
  }

  const features = data.features || {};
  const resolution = data.resolution || {};
  const isStale = data.last_updated
    ? (Date.now() - new Date(data.last_updated.replace(" ", "T") + "Z").getTime()) > 30 * 60 * 1000
    : true;

  // Detect arb mode: arb features have "ofi" or "state"
  const isArb = "ofi" in features || "state" in features || "completed" in resolution;
  const labels = isArb ? ARB_LABELS : PAPER_LABELS;
  const colorFn = isArb ? arbFeatureColor : (k: string, v: any) => paperFeatureColor(k, v as number);

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm text-muted-foreground">
            {isArb ? "OFI Monitor" : "Feature Monitor"}
          </CardTitle>
          {isStale && <span className="text-[10px] text-amber-400">STALE</span>}
        </div>
      </CardHeader>
      <CardContent className="text-xs font-mono space-y-1">
        {Object.entries(features).map(([key, val]) => (
          <div key={key} className="flex justify-between">
            <span className="text-muted-foreground">{labels[key] || key}</span>
            <span className={colorFn(key, val as any)}>{formatValue(key, val as any)}</span>
          </div>
        ))}

        {Object.keys(features).length > 0 && <Separator className="my-2" />}

        {isArb ? (
          <div className="space-y-1">
            <p className="text-muted-foreground text-[10px] uppercase tracking-widest">Activity</p>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Completed</span>
              <span className="text-emerald-400">{resolution.completed ?? 0}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Abandoned</span>
              <span className="text-amber-400">{resolution.abandoned ?? 0}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Instant Arbs</span>
              <span>{resolution.instant_arbs ?? 0}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Legs Opened</span>
              <span>{resolution.legs_opened ?? 0}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Success Rate</span>
              <span className={resolution.success_rate >= 50 ? "text-emerald-400" : "text-red-400"}>
                {resolution.success_rate?.toFixed(0) ?? 0}%
              </span>
            </div>
          </div>
        ) : (
          <div className="space-y-1">
            <p className="text-muted-foreground text-[10px] uppercase tracking-widest">Resolution</p>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Predictions</span>
              <span>{resolution.predictions ?? 0}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Results</span>
              <span>{resolution.results ?? 0}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Skips</span>
              <span>{resolution.skips ?? 0}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Rate</span>
              <span className={resolution.resolution_rate >= 90 ? "text-emerald-400" : "text-red-400"}>
                {resolution.resolution_rate?.toFixed(0) ?? 0}%
              </span>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
