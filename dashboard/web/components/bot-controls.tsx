"use client";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useBotStatus } from "@/hooks/use-bot-status";
import { fetchApi } from "@/lib/api";

export function BotControls() {
  const { data: status, mutate } = useBotStatus();
  const [loading, setLoading] = useState("");
  const [output, setOutput] = useState("");

  async function action(name: string, method: string, path: string) {
    setLoading(name);
    setOutput("");
    try {
      const res = await fetchApi<any>(path, { method });
      setOutput(res.stdout || res.stderr || "Done");
      mutate();
    } catch (e: any) {
      setOutput(`Error: ${e.message}`);
    }
    setLoading("");
  }

  return (
    <Card className="bg-zinc-900 border-zinc-800">
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm text-zinc-400">Bot Control</CardTitle>
          <Badge className={status?.running
            ? "bg-emerald-900 text-emerald-300"
            : "bg-red-900 text-red-300"}>
            {status?.running ? "RUNNING" : "STOPPED"}
          </Badge>
        </div>
        {status?.uptime && (
          <p className="text-xs text-zinc-600">since {status.uptime}</p>
        )}
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex gap-2 flex-wrap">
          <Button size="sm" variant="outline"
            className="border-emerald-700 text-emerald-400 hover:bg-emerald-900"
            disabled={!!loading}
            onClick={() => action("start", "POST", "/api/bot/start")}>
            {loading === "start" ? "..." : "Start"}
          </Button>
          <Button size="sm" variant="outline"
            className="border-red-700 text-red-400 hover:bg-red-900"
            disabled={!!loading}
            onClick={() => action("stop", "POST", "/api/bot/stop")}>
            {loading === "stop" ? "..." : "Stop"}
          </Button>
          <Button size="sm" variant="outline"
            className="border-amber-700 text-amber-400 hover:bg-amber-900"
            disabled={!!loading}
            onClick={() => action("restart", "POST", "/api/bot/restart")}>
            {loading === "restart" ? "..." : "Restart"}
          </Button>
          <Button size="sm" variant="outline"
            className="border-blue-700 text-blue-400 hover:bg-blue-900"
            disabled={!!loading}
            onClick={() => action("pull", "POST", "/api/bot/pull")}>
            {loading === "pull" ? "Pulling..." : "Git Pull"}
          </Button>
        </div>
        {output && (
          <pre className="text-xs bg-black/50 rounded p-2 text-zinc-400 max-h-24 overflow-auto">
            {output}
          </pre>
        )}
      </CardContent>
    </Card>
  );
}
