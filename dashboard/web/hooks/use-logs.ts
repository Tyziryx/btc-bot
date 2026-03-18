"use client";
import { useEffect, useRef, useState } from "react";
import { sseUrl } from "@/lib/api";

interface LogLine {
  timestamp: string;
  message: string;
  type: string;
}

export function useLiveLogs(maxLines = 150) {
  const [lines, setLines] = useState<LogLine[]>([]);
  const esRef = useRef<EventSource | null>(null);

  useEffect(() => {
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
      setTimeout(() => {
        esRef.current = new EventSource(sseUrl("/api/logs/stream"));
      }, 5000);
    };

    return () => es.close();
  }, [maxLines]);

  return lines;
}
