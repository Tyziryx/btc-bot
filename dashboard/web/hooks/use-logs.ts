"use client";
import { useEffect, useRef, useState, useCallback } from "react";
import { sseUrl } from "@/lib/api";

interface LogLine {
  timestamp: string;
  message: string;
  type: string;
}

export function useLiveLogs(maxLines = 200) {
  const [lines, setLines] = useState<LogLine[]>([]);
  const esRef = useRef<EventSource | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const connect = useCallback(() => {
    const es = new EventSource(sseUrl("/api/logs/stream"));
    esRef.current = es;

    es.onmessage = (event) => {
      try {
        const parsed: LogLine = JSON.parse(event.data);
        setLines((prev) => [...prev.slice(-maxLines), parsed]);
      } catch {}
    };

    es.onerror = () => {
      es.close();
      reconnectTimer.current = setTimeout(() => connect(), 5000);
    };
  }, [maxLines]);

  useEffect(() => {
    connect();
    return () => {
      esRef.current?.close();
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
    };
  }, [connect]);

  return lines;
}
