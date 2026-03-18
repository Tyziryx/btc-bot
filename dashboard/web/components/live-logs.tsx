"use client";
import { useEffect, useRef } from "react";
import { useLiveLogs } from "@/hooks/use-logs";
import { ScrollArea } from "@/components/ui/scroll-area";

const typeColors: Record<string, string> = {
  predict: "text-blue-400",
  win: "text-emerald-400",
  loss: "text-red-400",
  skip: "text-zinc-500",
  market: "text-amber-400",
  model: "text-purple-400",
  error: "text-red-500 font-bold",
  early: "text-cyan-400",
  features: "text-zinc-600",
  info: "text-zinc-400",
};

export function LiveLogs() {
  const lines = useLiveLogs(200);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [lines.length]);

  return (
    <ScrollArea className="h-96 rounded border border-zinc-800 bg-black/50 p-3 font-mono text-xs">
      {lines.length === 0 && (
        <p className="text-zinc-600 animate-pulse">Waiting for log stream...</p>
      )}
      {lines.map((l, i) => (
        <div key={i} className={`${typeColors[l.type] || "text-zinc-400"} leading-5`}>
          <span className="text-zinc-600 mr-2">{l.timestamp?.split(" ")[1] || ""}</span>
          {l.message}
        </div>
      ))}
      <div ref={bottomRef} />
    </ScrollArea>
  );
}
