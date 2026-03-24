# BTC Polymarket Arb Bot

## Deployment

Server: IONOS 217.154.8.243, user root, path /root/bot

**Deploy command (single command, does everything):**
```bash
bash deploy.sh
```

This does: git stash + pull, chmod all scripts, stop old services, clean old logs/trades, start arb bot (systemd), start dashboard (API + Next.js).

**Quick redeploy (code change only, keep data):**
```bash
cd /root/bot && git pull origin main && sudo systemctl restart btc-arb
```

**Dashboard only restart:**
```bash
chmod +x dashboard/*.sh && ./dashboard/stop-dashboard.sh && ./dashboard/start-dashboard.sh
```

## Architecture

- `bot/arb_trader.py` — Main arb bot. WebSocket CLOB for real-time orderbook. OFI from trade events. State machine: IDLE → LEG1_OPEN → COMPLETE/ABANDONED.
- `bot/arb_config.py` — Config dataclass (OFI threshold, bet size, max combined cost, etc.)
- `bot/polymarket.py` — Polymarket API: `find_market()` (Gamma), `ClobWebSocket` (real-time orderbook), REST fallback (`get_market_price`)
- `scripts/arb_trade.py` — Entry point, argparse, asyncio.run()
- `start-arb.sh` — systemd service setup (btc-arb)
- `deploy.sh` — One-command deploy (use `bash deploy.sh`, no chmod needed)

## Dashboard

- `dashboard/api/` — FastAPI backend (port 8888). Auto-detects arb vs paper trader mode.
- `dashboard/web/` — Next.js standalone (port 3000). Built locally, committed to git.
- `dashboard/start-dashboard.sh` — Starts API + Web. Access via ngrok tunnel only (port 3000 not publicly exposed)
- Next.js rewrites proxy `/api/*` → `localhost:8888`

## Key Rules

- Always `git stash` before `git pull` on server (untracked .next files conflict)
- Always `chmod +x` scripts after pull (git doesn't preserve execute bit on server)
- Always `git clean -fd dashboard/web/.next/standalone/` before pull (avoids merge conflicts)
- Build Next.js locally (`npm run build` in dashboard/web/), commit .next/, push
- Server has no Node.js build tools — only runs standalone
- Use `bash deploy.sh` not `./deploy.sh` to avoid chmod chicken-and-egg

## Data Files

- `data/logs/arb_*.log` — Arb bot logs (dashboard reads latest)
- `data/arb_trades.jsonl` — Trade records (dashboard reads for stats)
- Old paper trader files: `data/logs/bot_*.log`, `data/paper_trades.jsonl` (cleaned on deploy)
