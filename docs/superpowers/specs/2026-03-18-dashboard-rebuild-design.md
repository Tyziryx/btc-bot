# Dashboard Rebuild — shadcn Themed, Signal-Only Layout

**Date:** 2026-03-18
**Status:** Approved

## Goal

Rebuild the BTC bot dashboard using shadcn/ui consistently across all components. Replace hardcoded zinc colors with theme tokens. Add actionable charts (no decoration). Make logs a first-class debugging surface. Remove noise (hourly heatmap, daily bars).

## Data Sources

### Trade Record (paper_trades.jsonl)
Each trade contains: `window_id`, `timestamp`, `direction`, `prob`, `raw_prob`, `cal_prob_unclamped`, `confidence`, `edge`, `entry_price`, `price_source`, `gamma_price`, `bet_size`, `capital_before`, `actual`, `won`, `pnl`, `capital_after`, `window_open_price`, `window_close_price`.

**Note:** Older trades (from `.json` era) may lack `raw_prob`, `cal_prob_unclamped`, `price_source`, `gamma_price`. All frontend components must treat these as optional with fallback display (em-dash). The trade reader falls back to `paper_trades.json` if `.jsonl` is missing.

### Log Lines (bot_*.log)
Parsed types: `predict`, `win`, `loss`, `skip`, `market`, `model`, `error`, `early`, `features`, `info`.
FEATURES lines contain: hurst, rv_ratio, poc_distance, momentum, rsi, z_score, seasonal_wr.
MODEL lines contain: raw_prob, cal_prob, hurst, rv, poc values.

### API Endpoints
- `GET /api/trades?limit=N` → `{trades: [...], total: int}`
- `GET /api/stats` → stats object with capital_curve, KPIs
- `GET /api/logs?type=predict,error&search=hurst` → filtered log lines
- `GET /api/logs/stream` → SSE stream (with 30s heartbeat keepalive)
- `GET /api/features` → latest feature values + resolution stats (NEW)

## Layout (top → bottom)

### Row 1: Stats Cards (6 KPIs)
Capital | ROI | Total PnL | Win Rate | Max Drawdown | Profit Factor.
Use shadcn `Card` with `bg-card border-border`. Skeleton loading.

### Row 2: Capital Curve (full width)
Recharts AreaChart. shadcn Card wrapper with theme vars. Reference line at initial capital. Skeleton loading.

### Row 3: Two Charts (2 columns)
**Left — Win Rate Rolling (last 20 trades):** Recharts LineChart showing rolling WR as trades accumulate. Reference line at 50% (break-even). When line dips below 50%, visual alert. Empty state: "Need 5+ trades for rolling window."
**Right — Edge vs PnL Scatter:** Recharts ScatterChart. X = edge %, Y = PnL $. Color by win/loss. Shows if calculated edge is real. Skeleton loading.

### Row 4: Two Charts (2 columns)
**Left — PnL by Direction:** Two area lines (UP trades cumulative PnL, DOWN trades cumulative PnL). Shows directional bias. Skeleton loading.
**Right — Entry Price Distribution:** Recharts histogram (BarChart with dynamic bins). Bins auto-sized to actual data range with 0.01 granularity around the 0.48-0.55 range. Peak around $0.50 = good, $0.60+ = bad payoff. Skeleton loading.

### Row 5: Trades Table + Feature Monitor (3:1 split)
**Left (3/4 width) — Trades Table:** shadcn `Table` component. Columns: Time, Direction (Badge), Entry, Edge, Source, Bet, PnL, Capital, Result. Missing fields show em-dash.
**Right (1/4 width) — Feature Monitor:** Card showing latest feature values parsed from most recent FEATURES log line: hurst_500, rv_ratio, poc_distance, z_score, momentum, seasonal_wr. Plus resolution rate: PREDICT count vs RESULT count vs SKIP count. Stale indicator if features older than 30 min.

### Row 6: Live Logs (full width, prominent)
Full-width section. Height 500px. shadcn `Tabs` for filtering: All | Predictions | Wins/Losses | Errors.
Text search Input at top (client-side filtering on SSE stream). Sticky error Alert banner if recent errors detected. ScrollArea with auto-scroll.

## Components to Remove
- `hourly-heatmap.tsx` — not enough trades per hour for statistical significance
- Old `trade-analysis.tsx` — replaced by new chart components
- `model-monitor.tsx` — merged into new `feature-monitor.tsx`

## New Components to Create
- `win-rate-chart.tsx` — Rolling WR line chart
- `edge-scatter.tsx` — Edge vs PnL scatter plot
- `direction-pnl.tsx` — Cumulative PnL by UP/DOWN
- `entry-distribution.tsx` — Entry price histogram
- `feature-monitor.tsx` — Live feature values + resolution rate

## Components to Modify
- `stats-cards.tsx` — Theme vars, Skeleton loading
- `pnl-chart.tsx` — Theme vars, Skeleton loading
- `trades-table.tsx` — shadcn Table, theme vars, optional field handling
- `live-logs.tsx` — Full width, tabs filtering, search, error banner, 500px height, fix SSE reconnect bug
- `page.tsx` — New layout structure
- `layout.tsx` — Use `bg-background text-foreground`

## shadcn Components Used
Existing: Card, Badge, Table, Tabs, ScrollArea, Separator, Button.
To install: Skeleton, Input (for log search), Alert (for error banner).

## Theme Strategy
Replace all hardcoded colors with shadcn semantic tokens:
- `bg-zinc-900/80` → `bg-card`
- `border-zinc-800` → `border-border`
- `text-zinc-500` → `text-muted-foreground`
- `text-zinc-100` → `text-foreground`
- `bg-zinc-950` → `bg-background`
- `bg-zinc-800/50` → `bg-muted`

Keep trading-semantic colors as-is: emerald (win), red (loss), amber (neutral).

## API Changes

### Backend: New endpoint for feature data
`GET /api/features` — Parses latest FEATURES log line via regex + counts PREDICT/RESULT/SKIP occurrences. Only scans tail of log file (last 500 lines) for performance.

New function `parse_features_line(msg: str) -> dict` in `log_reader.py` extracts key=value pairs from FEATURES lines via regex: `r"(\w+)=([\d.\-]+)"`.

Response:
```json
{
  "features": {
    "hurst_500": 0.482,
    "rv_ratio": 1.23,
    "poc_distance": 0.15,
    "z_score": -0.3,
    "momentum_5m": 0.002,
    "seasonal_wr": 0.55
  },
  "resolution": {
    "predictions": 42,
    "results": 40,
    "skips": 5,
    "resolution_rate": 95.2
  },
  "last_updated": "2026-03-18T14:30:00Z"
}
```

### Backend: Enhanced log endpoint
`GET /api/logs?type=predict,error` — Server-side type filtering.

### Backend: SSE heartbeat
Add `:keepalive\n\n` comment every 30 seconds in `stream_logs` SSE generator to prevent ngrok idle timeouts.

### Backend: Trade reader resilience
- `read_trades()` falls back to `paper_trades.json` if `.jsonl` missing
- Remove `hourly` computation from `compute_stats` (no longer consumed)

### Frontend: New SWR hook
`useFeatures()` — polls `/api/features` every 15s.

### Frontend: Fix SSE reconnect bug
Current `use-logs.ts` reconnect creates new EventSource without re-wiring handlers. Extract setup into a function that wires both EventSource creation and handlers.

## Deployment
After rebuild: `npm run build` locally (standalone), commit `.next/standalone/`, push, restart on server via SSH. Build artifacts in git are intentional — the IONOS xs server (~512MB RAM) cannot run `npm install` or `npm run build`.

## What Stays Unchanged
- `lib/api.ts` — working correctly
- `hooks/use-trades.ts` — working correctly
- `next.config.ts` — standalone + rewrites working
- FastAPI main app structure
