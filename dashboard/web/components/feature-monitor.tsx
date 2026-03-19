"use client";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { useFeatures } from "@/hooks/use-features";

const FEATURE_LABELS: Record<string, string> = {
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

function featureColor(key: string, val: number): string {
  if (key.includes("hurst")) {
    if (Math.abs(val - 0.5) < 0.01) return "text-amber-400";
    return val > 0.5 ? "text-emerald-400" : "text-red-400";
  }
  if (key === "rv_ratio") return val > 1.5 ? "text-red-400" : val > 1 ? "text-amber-400" : "text-emerald-400";
  return "text-foreground";
}

export function FeatureMonitor() {
  const { data } = useFeatures();

  if (!data) {
    return (
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm text-muted-foreground">Feature Monitor</CardTitle>
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

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm text-muted-foreground">Feature Monitor</CardTitle>
          {isStale && <span className="text-[10px] text-amber-400">STALE</span>}
        </div>
      </CardHeader>
      <CardContent className="text-xs font-mono space-y-1">
        {Object.entries(features).map(([key, val]) => (
          <div key={key} className="flex justify-between">
            <span className="text-muted-foreground">{FEATURE_LABELS[key] || key}</span>
            <span className={featureColor(key, val as number)}>{(val as number).toFixed(3)}</span>
          </div>
        ))}

        {Object.keys(features).length > 0 && <Separator className="my-2" />}

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
      </CardContent>
    </Card>
  );
}
