#!/bin/bash
# Restart bot + dashboard after a code update.
# Keeps ngrok running (same URL).
#
# Usage after git pull:
#   ./restart-bot.sh

set -e
cd "$(dirname "$0")"

echo "=== Restarting bot + dashboard (keeping ngrok) ==="

# 1. Restart the trading bot
echo "[1/2] Restarting btc-bot service..."
sudo systemctl restart btc-bot
echo "  Bot restarted."

# 2. Restart dashboard (API + Web), ngrok stays alive
echo "[2/2] Restarting dashboard..."
./dashboard/start-dashboard.sh

echo ""
echo "=== All restarted! ==="
