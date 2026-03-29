// dashboard/web/components/tabs/signal-tab.tsx
"use client";
import { useFeatures } from "@/hooks/use-features";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";

function ConfBar({ score, threshold }: { score: number; threshold: number }) {
  const pct = Math.min(100, score);
  const threshPct = threshold;
  const color = score >= threshold ? "bg-emerald-400" : score >= threshold * 0.85 ? "bg-amber-400" : "bg-red-500";
  return (
    <div className="space-y-1">
      <div className="flex justify-between font-mono text-xs">
        <span className="text-muted-foreground">Confidence</span>
        <span className={score >= threshold ? "text-emerald-400 font-bold" : "text-amber-400 font-bold"}>
          {score.toFixed(0)}<span className="text-muted-foreground font-normal"> / {threshold} seuil</span>
        </span>
      </div>
      <div className="relative h-2 bg-muted rounded-full overflow-visible">
        <div className={`h-full ${color} rounded-full transition-all duration-300`} style={{ width: `${pct}%` }} />
        <div
          className="absolute -top-1 bottom-0 w-0.5 h-4 bg-amber-400"
          style={{ left: `${threshPct}%` }}
        />
      </div>
    </div>
  );
}

function ObShockBadge({ score }: { score: number }) {
  if (score === 0) return <span className="text-muted-foreground font-mono text-xs">0 / 3 — quiet</span>;
  if (score === 1) return <span className="text-amber-400 font-mono text-xs">1 / 3 — weak</span>;
  if (score === 2) return <span className="text-orange-400 font-bold font-mono text-xs">2 / 3 — signal ⚡</span>;
  return <span className="text-red-400 font-bold font-mono text-xs">3 / 3 — strong ⚡⚡</span>;
}

function MomentumIndicator({ score }: { score?: number }) {
  if (score == null) return <span className="text-muted-foreground font-mono text-xs">—</span>;
  if (score > 0.3) return <span className="text-emerald-400 font-mono text-xs">↑ UP bias ({score.toFixed(2)})</span>;
  if (score < -0.3) return <span className="text-red-400 font-mono text-xs">↓ DOWN bias ({score.toFixed(2)})</span>;
  return <span className="text-muted-foreground font-mono text-xs">→ neutral ({score.toFixed(2)})</span>;
}

const DECISION_COLOR: Record<string, string> = {
  ENTER_LEG1:    "text-emerald-400",
  INSTANT_ARB:   "text-emerald-400",
  COMPLETE_LEG2: "text-emerald-400",
  ABANDON:       "text-red-400",
  SKIP:          "text-muted-foreground",
};

export function SignalTab() {
  const { data } = useFeatures();
  if (!data) return <div className="text-muted-foreground font-mono text-xs p-4">Loading…</div>;

  const f = data.features ?? {};
  const sig = data.signal ?? {};
  const res = data.resolution ?? {};
  const isStale = data.last_updated
    ? Date.now() - new Date(data.last_updated.replace(" ", "T") + "Z").getTime() > 5 * 60_000
    : true;

  const recent: any[] = sig.recent_decisions ?? [];

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 pb-10">

      {/* ── Live signal panel ─────────────────────────────── */}
      <Card>
        <CardHeader className="pb-2">
          <div className="flex items-center justify-between">
            <CardTitle className="text-[10px] font-mono text-muted-foreground uppercase tracking-widest">
              Signal Live
            </CardTitle>
            {isStale
              ? <span className="text-[10px] text-amber-400 font-mono">STALE</span>
              : <span className="text-[10px] text-emerald-400 font-mono animate-pulse">● LIVE</span>
            }
          </div>
        </CardHeader>
        <CardContent className="space-y-3 font-mono text-xs">
          {f.confidence != null && (
            <ConfBar score={f.confidence} threshold={65} />
          )}
          <Separator />
          {[
            ["TFI",      f.tfi != null ? (f.tfi >= 0 ? `+${f.tfi.toFixed(1)}` : f.tfi.toFixed(1)) : "—"],
            ["OBI",      f.obi != null ? (f.obi >= 0 ? `+${f.obi.toFixed(3)}` : f.obi.toFixed(3)) : "—"],
            ["UP Ask",   f.up_ask   != null ? `$${f.up_ask.toFixed(3)}`   : "—"],
            ["DOWN Ask", f.down_ask != null ? `$${f.down_ask.toFixed(3)}` : "—"],
            ["Combined", f.combined != null ? `$${f.combined.toFixed(3)}` : "—"],
            ["State",    f.state ?? "—"],
          ].map(([k, v]) => (
            <div key={k as string} className="flex justify-between">
              <span className="text-muted-foreground">{k}</span>
              <span className={
                k === "Combined" && f.combined < 0.95 ? "text-emerald-400" :
                k === "State" && f.state === "LEG1_OPEN" ? "text-amber-400" :
                "text-foreground"
              }>{v}</span>
            </div>
          ))}
          <Separator />
          <div className="flex justify-between">
            <span className="text-muted-foreground">OB Shock</span>
            <ObShockBadge score={f.ob_shock ?? 0} />
          </div>
          <div className="flex justify-between">
            <span className="text-muted-foreground">Momentum</span>
            <MomentumIndicator score={f.momentum_score} />
          </div>
          {data.last_updated && (
            <p className="text-[9px] text-muted-foreground pt-1">
              Updated {data.last_updated.split(" ")[1]}
            </p>
          )}
        </CardContent>
      </Card>

      {/* ── Decision log ──────────────────────────────────── */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-[10px] font-mono text-muted-foreground uppercase tracking-widest">
            Recent Decisions
          </CardTitle>
        </CardHeader>
        <CardContent className="font-mono text-xs space-y-2">
          {sig.last_action && (
            <div className="bg-muted rounded p-2 space-y-1">
              <div className="flex justify-between">
                <span className="text-muted-foreground">Last action</span>
                <span className={DECISION_COLOR[sig.last_action] ?? "text-foreground"}>
                  {sig.last_action}
                  {sig.last_reason ? ` (${sig.last_reason})` : ""}
                </span>
              </div>
              {sig.last_score != null && (
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Score</span>
                  <span className={sig.last_score >= 65 ? "text-emerald-400" : "text-amber-400"}>
                    {Number(sig.last_score).toFixed(1)}
                  </span>
                </div>
              )}
              {sig.last_ts && (
                <div className="flex justify-between">
                  <span className="text-muted-foreground">At</span>
                  <span className="text-muted-foreground text-[10px]">{sig.last_ts.split(" ")[1]}</span>
                </div>
              )}
            </div>
          )}
          <Separator />
          <div className="space-y-1 max-h-52 overflow-y-auto pr-1">
            {recent.length === 0 && (
              <p className="text-muted-foreground">No decisions yet…</p>
            )}
            {recent.map((d: any, i: number) => (
              <div key={i} className={`${DECISION_COLOR[d.action] ?? "text-muted-foreground"} text-[10px]`}>
                <span className="text-muted-foreground mr-2">{d._ts?.split(" ")[1] ?? ""}</span>
                {d.action}
                {d.reason ? ` · ${d.reason}` : ""}
                {d.score != null ? ` · ${Number(d.score).toFixed(0)}` : ""}
              </div>
            ))}
          </div>
          <Separator />
          <div className="grid grid-cols-2 gap-2 pt-1">
            {[
              ["Completed", res.completed ?? 0, "text-emerald-400"],
              ["Abandoned", res.abandoned ?? 0, "text-red-400"],
              ["Arbs",      res.instant_arbs ?? 0, "text-emerald-400"],
              ["Win Rate",  (res.win_rate ?? 0).toFixed(0) + "%", (res.win_rate ?? 0) >= 55 ? "text-emerald-400" : "text-amber-400"],
            ].map(([label, value, color]) => (
              <div key={label as string} className="bg-muted rounded p-2">
                <p className="text-[9px] text-muted-foreground uppercase">{label}</p>
                <p className={`text-sm font-bold ${color}`}>{value}</p>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
