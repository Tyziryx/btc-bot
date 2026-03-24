"use client";
import { useMemo, useState } from "react";
import { useLiveLogs } from "@/hooks/use-logs";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Input } from "@/components/ui/input";
import { Alert, AlertTitle, AlertDescription } from "@/components/ui/alert";

const typeColors: Record<string, string> = {
  // Arb types
  tick: "text-muted-foreground opacity-50",
  leg: "text-blue-400",
  hunting: "text-amber-400",
  complete: "text-emerald-400 font-bold",
  abandoned: "text-red-400",
  instant_arb: "text-emerald-400 font-bold",
  window: "text-cyan-400",
  // Paper trader types
  predict: "text-blue-400",
  win: "text-emerald-400",
  loss: "text-red-400",
  skip: "text-muted-foreground",
  market: "text-amber-400",
  model: "text-purple-400",
  early: "text-cyan-400",
  features: "text-muted-foreground opacity-60",
  // Shared
  error: "text-red-500 font-bold",
  info: "text-muted-foreground",
};

const TAB_FILTERS: Record<string, string[]> = {
  all: [],
  trades: ["leg", "complete", "abandoned", "instant_arb", "predict", "win", "loss"],
  hunting: ["hunting", "tick"],
  errors: ["error"],
};

export function LiveLogs() {
  const lines = useLiveLogs(300);
  const [search, setSearch] = useState("");
  const [tab, setTab] = useState("all");

  const filtered = useMemo(() => {
    let result = lines;
    const allowedTypes = TAB_FILTERS[tab];
    if (allowedTypes && allowedTypes.length > 0) {
      result = result.filter((l) => allowedTypes.includes(l.type));
    }
    if (search) {
      const q = search.toLowerCase();
      result = result.filter((l) => l.message.toLowerCase().includes(q));
    }
    // Newest first
    return [...result].reverse();
  }, [lines, tab, search]);

  const recentErrors = lines.filter((l) => l.type === "error").slice(-5);
  const hasRecentErrors = recentErrors.length > 0;

  return (
    <div className="space-y-3">
      {hasRecentErrors && (
        <Alert variant="destructive">
          <AlertTitle>Errors detected</AlertTitle>
          <AlertDescription className="text-xs font-mono truncate">
            {recentErrors[recentErrors.length - 1]?.message}
          </AlertDescription>
        </Alert>
      )}

      <div className="flex items-center gap-3">
        <Tabs value={tab} onValueChange={setTab} className="flex-1">
          <TabsList variant="line">
            <TabsTrigger value="all">All</TabsTrigger>
            <TabsTrigger value="trades">Trades</TabsTrigger>
            <TabsTrigger value="hunting">Hunting</TabsTrigger>
            <TabsTrigger value="errors">Errors</TabsTrigger>
          </TabsList>
        </Tabs>
        <Input
          placeholder="Search logs..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="w-48 h-8 text-xs"
        />
      </div>

      <ScrollArea className="h-[500px] rounded-lg border border-border bg-card p-3 font-mono text-xs">
        {filtered.length === 0 && (
          <p className="text-muted-foreground animate-pulse">
            {lines.length === 0 ? "Waiting for log stream..." : "No matching logs"}
          </p>
        )}
        {filtered.map((l, i) => (
          <div key={i} className={`${typeColors[l.type] || "text-muted-foreground"} leading-5`}>
            <span className="text-muted-foreground/50 mr-2">{l.timestamp?.split(" ")[1] || ""}</span>
            {l.message}
          </div>
        ))}
      </ScrollArea>
    </div>
  );
}
