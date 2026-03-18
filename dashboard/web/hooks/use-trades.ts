import useSWR from "swr";
import { fetchApi } from "@/lib/api";

export function useStats() {
  return useSWR("/api/stats", (url) => fetchApi<any>(url), {
    refreshInterval: 15_000,
  });
}

export function useTrades(limit = 50) {
  return useSWR(`/api/trades?limit=${limit}`, (url) => fetchApi<any>(url), {
    refreshInterval: 15_000,
  });
}
