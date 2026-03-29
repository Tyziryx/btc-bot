// dashboard/web/components/tabs/trades-tab.tsx
"use client";
import { useState } from "react";
import { TradesTable } from "@/components/trades-table";

type Filter = "all" | "win" | "lose" | "abandoned" | "complete";

const FILTERS: { key: Filter; label: string; color: string }[] = [
  { key: "all",       label: "Tous",    color: "bg-muted text-foreground" },
  { key: "win",       label: "WIN",     color: "bg-emerald-400/20 text-emerald-400 border-emerald-400/30" },
  { key: "lose",      label: "LOSE",    color: "bg-red-400/20 text-red-400 border-red-400/30" },
  { key: "abandoned", label: "ABD",     color: "bg-amber-400/20 text-amber-400 border-amber-400/30" },
  { key: "complete",  label: "ARB",     color: "bg-violet-400/20 text-violet-400 border-violet-400/30" },
];

export function TradesTab() {
  const [filter, setFilter] = useState<Filter>("all");

  return (
    <div className="space-y-4 pb-10">
      <div className="flex gap-2 font-mono text-[10px]">
        {FILTERS.map(({ key, label, color }) => (
          <button
            key={key}
            onClick={() => setFilter(key)}
            className={`px-3 py-1 rounded-sm border transition-opacity ${color} ${
              filter === key ? "opacity-100" : "opacity-40 hover:opacity-70"
            }`}
          >
            {label}
          </button>
        ))}
      </div>
      <TradesTable statusFilter={filter === "all" ? undefined : filter} />
    </div>
  );
}
