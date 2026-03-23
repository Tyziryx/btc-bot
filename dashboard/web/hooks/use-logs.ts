"use client";
import { useEffect, useRef, useState } from "react";
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
