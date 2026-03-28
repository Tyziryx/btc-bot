#!/bin/bash
# One-command deploy: pull, chmod, clean old data, start arb bot + dashboard
# Usage: bash deploy.sh   (no need for chmod — always use 'bash')

set -e
cd "$(dirname "$0")"

echo "=== DEPLOY ==="

# 1. Pull latest code
echo "[1/6] Pulling latest code..."
git stash 2>/dev/null || true
git clean -fd dashboard/web/.next/standalone/ 2>/dev/null || true
git pull origin main

# 2. Fix permissions (the whole point of this script)
echo "[2/6] Fixing permissions..."
chmod +x dashboard/*.sh start-arb.sh deploy.sh 2>/dev/null || true
chmod +x start.sh stop.sh status.sh logs.sh restart-bot.sh 2>/dev/null || true

# 3. Stop old services
echo "[3/6] Stopping old services..."
sudo systemctl stop btc-bot 2>/dev/null || true
sudo systemctl stop btc-arb 2>/dev/null || true
./dashboard/stop-dashboard.sh 2>/dev/null || true

# 4. Backup data then clean
echo "[4/6] Backing up data before clean..."
if [[ -f fetch-server-data.sh ]]; then
    bash fetch-server-data.sh --pre-deploy || echo "[WARN] Backup failed — continuing anyway"
fi
echo "[4/6] Cleaning old logs..."
rm -f data/logs/bot_*.log data/logs/arb_*.log
rm -f data/paper_trades.jsonl data/arb_trades.jsonl

# 5. Start arb bot
echo "[5/6] Starting arb bot..."
./start-arb.sh

# 6. Start dashboard
echo "[6/6] Starting dashboard..."
./dashboard/start-dashboard.sh

echo ""
echo "=== DEPLOY COMPLETE ==="
echo ""
echo "  Arb bot: journalctl -u btc-arb -f"
echo "  Dashboard logs: tail -f /tmp/dashboard-api.log /tmp/dashboard-web.log"
echo "  Redeploy: bash deploy.sh"
