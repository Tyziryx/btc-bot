// dashboard/web/hooks/use-logs.ts
"use client";
import { useEffect, useRef, useState } from "react";
import { fetchApi } from "@/lib/api";

export interface LogLine {
  timestamp: string;
  message: string;
  type: string;
}

export function useLiveLogs(maxLines = 200): LogLine[] {
  const [lines, setLines] = useState<LogLine[]>([]);
  const bufRef = useRef<LogLine[]>([]);

  useEffect(() => {
    // Seed with existing logs
    fetchApi<{ lines: LogLine[] }>("/api/logs?limit=100")
      .then((d) => {
        if (d.lines?.length) {
          bufRef.current = d.lines.slice(-maxLines);
          setLines([...bufRef.current]);
        }
      })
      .catch(() => {});

    // SSE stream
    const es = new EventSource("/api/logs/stream");

    es.onmessage = (ev) => {
      try {
        const line: LogLine = JSON.parse(ev.data);
        if (!line.message) return;
        bufRef.current = [...bufRef.current, line].slice(-maxLines);
        setLines([...bufRef.current]);
      } catch {
        /* ignore parse errors */
      }
    };

    es.onerror = () => {
      es.close();
    };

    return () => es.close();
  }, [maxLines]);

  return lines;
}

export function useWindowLogs(windowId: number | null) {
  const [lines, setLines] = useState<LogLine[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!windowId) { setLines([]); return; }
    setLoading(true);
    fetchApi<{ lines: LogLine[] }>(`/api/logs/window/${windowId}`)
      .then((d) => setLines(d.lines ?? []))
      .catch(() => setLines([]))
      .finally(() => setLoading(false));
  }, [windowId]);

  return { lines, loading };
}
