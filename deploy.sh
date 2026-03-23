#!/bin/bash
# One-command deploy: pull, chmod, clean old data, start arb bot + dashboard
# Usage: bash deploy.sh   (no need for chmod — always use 'bash')

set -e
cd "$(dirname "$0")"

echo "=== DEPLOY ==="

# 1. Pull latest code
echo "[1/5] Pulling latest code..."
git stash 2>/dev/null || true
git pull origin main

# 2. Fix permissions (the whole point of this script)
echo "[2/5] Fixing permissions..."
chmod +x dashboard/*.sh start-arb.sh 2>/dev/null || true
chmod +x start.sh stop.sh status.sh logs.sh restart-bot.sh 2>/dev/null || true

# 3. Stop old services
echo "[3/5] Stopping old services..."
sudo systemctl stop btc-bot 2>/dev/null || true
./dashboard/stop-dashboard.sh 2>/dev/null || true

# 4. Clean old paper trader data (keep arb data)
echo "[4/5] Cleaning old paper trader logs..."
rm -f data/logs/bot_*.log data/paper_trades.jsonl

# 5. Start arb bot + dashboard
echo "[5/5] Starting arb bot + dashboard..."
./start-arb.sh
./dashboard/start-dashboard.sh

echo ""
echo "=== DEPLOY COMPLETE ==="
