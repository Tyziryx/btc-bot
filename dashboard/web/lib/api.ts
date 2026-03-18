const API_BASE = process.env.NEXT_PUBLIC_API_URL || "";

export async function fetchApi<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, options);
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json();
}

export function sseUrl(path: string): string {
  return `${API_BASE}${path}`;
}
