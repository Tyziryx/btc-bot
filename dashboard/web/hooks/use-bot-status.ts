import useSWR from "swr";
import { fetchApi } from "@/lib/api";

export function useBotStatus() {
  return useSWR("/api/bot/status", (url) => fetchApi<any>(url), {
    refreshInterval: 10_000,
  });
}
