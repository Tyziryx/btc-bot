// dashboard/web/components/tabs/logs-tab.tsx
"use client";
import { useMemo, useState, useRef, useEffect } from "react";
import { useLiveLogs } from "@/hooks/use-logs";
import { Input } from "@/components/ui/input";

const TYPE_COLOR: Record<string, string> = {
  tick:        "text-muted-foreground opacity-40",
  leg:         "text-blue-400",
  hunting:     "text-amber-400",
  complete:    "text-emerald-400 font-bold",
  abandoned:   "text-red-400",
  instant_arb: "text-emerald-400 font-bold",
  win:         "text-emerald-400 font-bold",
  lose:        "text-red-400 font-bold",
  window:      "text-cyan-400",
  decision:    "text-violet-400",
  error:       "text-red-500 font-bold",
  skip:        "text-muted-foreground",
  info:        "text-muted-foreground",
};

const TABS = [
  { key: "all",      label: "Tout" },
  { key: "trades",   label: "Trades" },
  { key: "decision", label: "Décisions" },
  { key: "error",    label: "Erreurs" },
];

const TRADE_TYPES = ["leg", "complete", "abandoned", "instant_arb", "win", "lose"];

export function LogsTab() {
  const lines = useLiveLogs(300);
  const [tab, setTab] = useState("all");
  const [search, setSearch] = useState("");
  const [paused, setPaused] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!paused && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [lines, paused]);

  const filtered = useMemo(() => {
    let result = [...lines].reverse();
    if (tab === "trades")   result = result.filter((l) => TRADE_TYPES.includes(l.type));
    if (tab === "decision") result = result.filter((l) => l.type === "decision");
    if (tab === "error")    result = result.filter((l) => l.type === "error");
    if (search) {
      const q = search.toLowerCase();
      result = result.filter((l) => l.message.toLowerCase().includes(q));
    }
    return result;
  }, [lines, tab, search]);

  return (
    <div className="space-y-3 pb-10">
      <div className="flex items-center gap-3">
        <div className="flex gap-1 font-mono text-[10px]">
          {TABS.map(({ key, label }) => (
            <button
              key={key}
              onClick={() => setTab(key)}
              className={`px-3 py-1 rounded-sm border border-border transition-colors ${
                tab === key
                  ? "bg-primary text-primary-foreground border-primary"
                  : "bg-card text-muted-foreground hover:text-foreground"
              }`}
            >
              {label}
            </button>
          ))}
        </div>
        <Input
          placeholder="Rechercher…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="w-44 h-7 text-[10px] font-mono bg-card border-border"
        />
        <button
          onClick={() => setPaused((p) => !p)}
          className={`px-3 py-1 rounded-sm border text-[10px] font-mono ${
            paused
              ? "bg-amber-400/20 text-amber-400 border-amber-400/30"
              : "bg-card text-muted-foreground border-border"
          }`}
        >
          {paused ? "▶ Resume" : "⏸ Pause"}
        </button>
        <span className="text-[10px] text-muted-foreground font-mono ml-auto">
          {lines.length} lignes
        </span>
      </div>

      <div
        ref={scrollRef}
        className="h-[600px] overflow-y-auto rounded border border-border bg-card p-3 font-mono text-[11px] leading-5"
      >
        {filtered.length === 0 ? (
          <p className="text-muted-foreground animate-pulse">
            {lines.length === 0 ? "En attente du stream SSE…" : "Aucun log correspondant"}
          </p>
        ) : (
          filtered.map((l, i) => (
            <div key={i} className={TYPE_COLOR[l.type] ?? "text-muted-foreground"}>
              <span className="text-muted-foreground/40 mr-2 select-none text-[10px]">
                {l.timestamp?.split(" ")[1] ?? ""}
              </span>
              {l.message}
            </div>
          ))
        )}
      </div>
    </div>
  );
}
