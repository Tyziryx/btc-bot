"use client";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { useFeatures } from "@/hooks/use-features";

const ARB_LABELS: Record<string, string> = {
  tfi: "TFI",
  ofi: "TFI",          // backward compat alias
  obi: "OBI",
  confidence: "Confidence",
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

// Order in which to display arb features
const ARB_FEATURE_ORDER = ["confidence", "tfi", "obi", "up_ask", "down_ask", "combined", "state"];

function confidenceColor(score: number): string {
  if (score >= 65) return "text-emerald-400";
  if (score >= 40) return "text-amber-400";
  return "text-red-400";
}

function arbFeatureColor(key: string, val: number | string): string {
  if (key === "confidence") {
    const n = typeof val === "number" ? val : parseFloat(val as string);
    return confidenceColor(n);
  }
  if (key === "tfi" || key === "ofi") {
    const n = typeof val === "number" ? val : parseFloat(val as string);
    if (Math.abs(n) >= 50) return "text-amber-400";
    return "text-muted-foreground";
  }
  if (key === "obi") {
    const n = typeof val === "number" ? val : parseFloat(val as string);
    if (Math.abs(n) >= 0.3) return "text-amber-400";
    return "text-muted-foreground";
  }
  if (key === "combined") {
    const n = typeof val === "number" ? val : parseFloat(val as string);
    if (n < 0.97) return "text-emerald-400";
    if (n < 0.99) return "text-amber-400";
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
    if (key === "confidence") return val.toFixed(0) + "/100";
    if (key === "tfi" || key === "ofi") return val >= 0 ? `+${val.toFixed(1)}` : val.toFixed(1);
    if (key === "obi") return val >= 0 ? `+${val.toFixed(3)}` : val.toFixed(3);
    return val.toFixed(3);
  }
  return String(val);
}

function DecisionReasonBadge({ action, reason }: { action?: string; reason?: string }) {
  if (!action) return null;
  const label = action === "SKIP" && reason ? `SKIP: ${reason}` : action;
  const color =
    action === "ENTER_LEG1" || action === "INSTANT_ARB" || action === "COMPLETE_LEG2"
      ? "text-emerald-400"
      : action === "ABANDON"
      ? "text-red-400"
      : action === "SKIP"
      ? "text-muted-foreground"
      : "text-amber-400";
  return <span className={`${color} font-mono text-[10px] truncate max-w-[140px]`}>{label}</span>;
}

export function FeatureMonitor() {
  const { data } = useFeatures();

  if (!data) {
    return (
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm text-muted-foreground">Signal Monitor</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          {Array.from({ length: 8 }).map((_, i) => (
            <Skeleton key={i} className="h-4 w-full" />
          ))}
        </CardContent>
      </Card>
    );
  }

  const features = data.features || {};
  const resolution = data.resolution || {};
  const signal = data.signal || {};
  const isStale = data.last_updated
    ? (Date.now() - new Date(data.last_updated.replace(" ", "T") + "Z").getTime()) > 5 * 60 * 1000
    : true;

  const isArb = "tfi" in features || "ofi" in features || "state" in features || "completed" in resolution;
  const colorFn = isArb ? arbFeatureColor : (k: string, v: any) => paperFeatureColor(k, v as number);

  // For arb mode: show features in preferred order, deduplicated (skip legacy "ofi" if "tfi" present)
  const featureEntries = isArb
    ? ARB_FEATURE_ORDER
        .filter((k) => k in features && !(k === "ofi" && "tfi" in features))
        .map((k) => [k, features[k]] as [string, any])
    : Object.entries(features);

  const confScore = typeof features.confidence === "number" ? features.confidence : null;

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm text-muted-foreground">
            {isArb ? "Signal Monitor" : "Feature Monitor"}
          </CardTitle>
          {isStale && <span className="text-[10px] text-amber-400">STALE</span>}
        </div>
      </CardHeader>
      <CardContent className="text-xs font-mono space-y-1">

        {/* Confidence score bar (arb only) */}
        {isArb && confScore !== null && (
          <div className="mb-2">
            <div className="flex justify-between mb-1">
              <span className="text-muted-foreground text-[10px] uppercase tracking-widest">Confidence</span>
              <span className={`font-bold ${confidenceColor(confScore)}`}>{confScore.toFixed(0)}/100</span>
            </div>
            <div className="w-full h-1.5 bg-muted rounded-full overflow-hidden">
              <div
                className={`h-full rounded-full transition-all duration-500 ${
                  confScore >= 65 ? "bg-emerald-400" : confScore >= 40 ? "bg-amber-400" : "bg-red-500"
                }`}
                style={{ width: `${Math.min(100, confScore)}%` }}
              />
            </div>
            {/* Threshold marker */}
            <div className="relative h-1 mt-0.5">
              <div className="absolute h-2 w-0.5 bg-amber-400/70 -top-0.5" style={{ left: "65%" }} />
            </div>
          </div>
        )}

        {featureEntries.map(([key, val]) => (
          <div key={key} className="flex justify-between">
            <span className="text-muted-foreground">
              {isArb ? (ARB_LABELS[key] || key) : (PAPER_LABELS[key] || key)}
            </span>
            <span className={colorFn(key, val as any)}>{formatValue(key, val as any)}</span>
          </div>
        ))}

        {featureEntries.length > 0 && <Separator className="my-2" />}

        {isArb ? (
          <div className="space-y-1">
            <p className="text-muted-foreground text-[10px] uppercase tracking-widest">Activity</p>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Completed</span>
              <span className="text-emerald-400">{resolution.completed ?? 0}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Abandoned</span>
              <span className="text-red-400">{resolution.abandoned ?? 0}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Instant Arbs</span>
              <span className="text-emerald-400">{resolution.instant_arbs ?? 0}</span>
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

            {/* Last DECISION reason */}
            {signal.last_action && (
              <>
                <Separator className="my-2" />
                <p className="text-muted-foreground text-[10px] uppercase tracking-widest">Last Decision</p>
                <div className="flex justify-between items-start gap-1">
                  <span className="text-muted-foreground shrink-0">Action</span>
                  <DecisionReasonBadge action={signal.last_action} reason={signal.last_reason} />
                </div>
                {signal.last_score != null && (
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">Score</span>
                    <span className={confidenceColor(signal.last_score)}>
                      {Number(signal.last_score).toFixed(1)}
                    </span>
                  </div>
                )}
                {signal.last_ts && (
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">At</span>
                    <span className="text-muted-foreground text-[10px]">
                      {signal.last_ts?.split(" ")[1] || signal.last_ts}
                    </span>
                  </div>
                )}
              </>
            )}
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
