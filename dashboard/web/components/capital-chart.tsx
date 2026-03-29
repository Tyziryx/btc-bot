"use client";
import { useEffect, useRef } from "react";
import { createChart, ColorType, LineStyle, AreaSeries, LineSeries } from "lightweight-charts";
import { useStats } from "@/hooks/use-trades";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

export function CapitalChart() {
  const { data } = useStats();
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<ReturnType<typeof createChart> | null>(null);
  const seriesRef = useRef<any>(null);

  // Create chart once on mount
  useEffect(() => {
    if (!containerRef.current) return;

    const chart = createChart(containerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: "#556677",
        fontFamily: "JetBrains Mono, monospace",
        fontSize: 10,
      },
      grid: {
        vertLines: { color: "#1a3a5c", style: LineStyle.Dotted },
        horzLines: { color: "#1a3a5c", style: LineStyle.Dotted },
      },
      crosshair: {
        vertLine: { color: "#334455", width: 1, style: LineStyle.Solid },
        horzLine: { color: "#334455", width: 1, style: LineStyle.Solid },
      },
      rightPriceScale: { borderColor: "#1a3a5c" },
      timeScale: {
        borderColor: "#1a3a5c",
        timeVisible: true,
        secondsVisible: false,
      },
      width: containerRef.current.clientWidth,
      height: 220,
      handleScroll: true,
      handleScale: true,
    });

    chartRef.current = chart;

    const series = chart.addSeries(AreaSeries, {
      lineColor: "#00ff88",
      topColor: "rgba(0,255,136,0.18)",
      bottomColor: "rgba(0,255,136,0.00)",
      lineWidth: 2,
      priceFormat: { type: "price", precision: 2, minMove: 0.01 },
    });
    seriesRef.current = series;

    const onResize = () => {
      if (containerRef.current && chartRef.current) {
        chartRef.current.applyOptions({ width: containerRef.current.clientWidth });
      }
    };
    window.addEventListener("resize", onResize);

    return () => {
      window.removeEventListener("resize", onResize);
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
    };
  }, []);

  // Update data whenever stats change
  useEffect(() => {
    if (!data?.capital_curve?.length || !seriesRef.current || !chartRef.current) return;

    const seen = new Set<number>();
    const points = data.capital_curve
      .filter((p: any) => p.ts && p.capital != null)
      .map((p: any) => ({
        time: Math.floor(new Date(p.ts).getTime() / 1000) as number,
        value: parseFloat(Number(p.capital).toFixed(2)),
      }))
      .filter((p: { time: number; value: number }) => {
        if (seen.has(p.time)) return false;
        seen.add(p.time);
        return true;
      })
      .sort((a: { time: number }, b: { time: number }) => a.time - b.time);

    if (points.length === 0) return;

    seriesRef.current.setData(points);

    if (data.initial_capital) {
      const refLine = chartRef.current.addSeries(LineSeries, {
        color: "#334455",
        lineStyle: LineStyle.Dashed,
        lineWidth: 1,
        lastValueVisible: false,
        priceLineVisible: false,
        crosshairMarkerVisible: false,
      });
      refLine.setData([
        { time: points[0].time, value: data.initial_capital },
        { time: points[points.length - 1].time, value: data.initial_capital },
      ]);
    }

    chartRef.current.timeScale().fitContent();
  }, [data]);

  if (!data) {
    return (
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-[10px] font-mono text-muted-foreground uppercase tracking-widest">
            Capital Curve
          </CardTitle>
        </CardHeader>
        <CardContent>
          <Skeleton className="h-[220px] w-full" />
        </CardContent>
      </Card>
    );
  }

  const isUp = data.capital >= data.initial_capital;

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-[10px] font-mono text-muted-foreground uppercase tracking-widest">
            Capital Curve
          </CardTitle>
          <div className="flex items-center gap-4 font-mono text-xs">
            <span className="text-muted-foreground">${data.initial_capital.toFixed(2)} →</span>
            <span className={`text-sm font-bold ${isUp ? "text-emerald-400" : "text-red-400"}`}>
              ${data.capital.toFixed(2)}
            </span>
            <span className={isUp ? "text-emerald-400" : "text-red-400"}>
              {data.roi >= 0 ? "+" : ""}{data.roi.toFixed(2)}%
            </span>
          </div>
        </div>
      </CardHeader>
      <CardContent className="p-0 px-2 pb-2">
        <div ref={containerRef} className="w-full" />
      </CardContent>
    </Card>
  );
}
