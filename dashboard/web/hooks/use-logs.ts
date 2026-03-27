"use client";
import { useEffect, useRef, useState, useCallback } from "react";
import { fetchApi } from "@/lib/api";

interface LogLine {
  timestamp: string;
  message: string;
  type: string;
}

export function useLiveLogs(maxLines = 200) {
  const [lines, setLines] = useState<LogLine[]>([]);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    const poll = () => {
      fetchApi<{ lines: LogLine[] }>("/api/logs?limit=200")
        .then((data) => {
          if (data.lines?.length) {
            setLines(data.lines);
          }
        })
        .catch(() => {});
    };

    // Initial fetch
    poll();

    // Poll every 5 seconds
    intervalRef.current = setInterval(poll, 5000);

    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
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
      .then((data) => setLines(data.lines ?? []))
      .catch(() => setLines([]))
      .finally(() => setLoading(false));
  }, [windowId]);

  return { lines, loading };
}
