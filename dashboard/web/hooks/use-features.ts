import useSWR from "swr";
import { fetchApi } from "@/lib/api";

export function useFeatures() {
  return useSWR("/api/features", (url) => fetchApi<any>(url), {
    refreshInterval: 15_000,
  });
}
