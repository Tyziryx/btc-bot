#!/bin/bash
# Deployment script for BTC Paper Trading Bot
# Run this ON the IONOS server after uploading the BOT folder

set -e

echo "=========================================="
echo "  BTC Paper Trading Bot - Setup"
echo "=========================================="

cd "$(dirname "$0")/.."
BOT_DIR="$(pwd)"

# Install Python + venv if needed
echo "[1/4] Installing system dependencies..."
sudo apt update -qq
sudo apt install -y -qq python3 python3-pip python3-venv > /dev/null 2>&1

# Create virtual environment
echo "[2/4] Creating Python virtual environment..."
python3 -m venv venv
source venv/bin/activate
pip install --quiet -r requirements.txt

# Create systemd service
echo "[3/4] Installing systemd service..."
sudo tee /etc/systemd/system/btc-paper-trader.service > /dev/null <<EOF
[Unit]
Description=BTC Paper Trading Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$(whoami)
WorkingDirectory=$BOT_DIR
ExecStart=$BOT_DIR/venv/bin/python -u scripts/paper_trade.py --duration 0
Restart=always
RestartSec=30
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable btc-paper-trader

# Create convenience commands
echo "[4/4] Creating helper scripts..."

# Start bot
cat > "$BOT_DIR/start.sh" <<'EOF'
#!/bin/bash
sudo systemctl start btc-paper-trader
echo "Bot started! Check status with: ./status.sh"
EOF

# Stop bot
cat > "$BOT_DIR/stop.sh" <<'EOF'
#!/bin/bash
sudo systemctl stop btc-paper-trader
echo "Bot stopped."
EOF

# Status + live stats
cat > "$BOT_DIR/status.sh" <<'EOF'
#!/bin/bash
echo "=========================================="
echo "  BOT SERVICE STATUS"
echo "=========================================="
sudo systemctl status btc-paper-trader --no-pager -l 2>/dev/null | head -15
echo ""

# Show trade stats
cd "$(dirname "$0")"
if [ -f data/paper_trades.json ]; then
    python3 -c "
import json
with open('data/paper_trades.json') as f:
    trades = json.load(f)
wins = sum(1 for t in trades if t['won'])
losses = len(trades) - wins
pnl = sum(t['pnl'] for t in trades)
wr = wins/len(trades)*100 if trades else 0
print('==========================================')
print('  PAPER TRADING STATS')
print('==========================================')
print('  Trades: %d (wins: %d, losses: %d)' % (len(trades), wins, losses))
print('  Win rate: %.1f%%' % wr)
print('  Total PnL: \$%.2f' % pnl)
print('  Capital: \$%.2f' % trades[-1]['capital_after'])
print('  First trade: %s' % trades[0]['timestamp'][:16])
print('  Last trade:  %s' % trades[-1]['timestamp'][:16])
print('==========================================')
" 2>/dev/null
else
    echo "  No trades yet - bot is warming up..."
fi
EOF

# View recent logs
cat > "$BOT_DIR/logs.sh" <<'EOF'
#!/bin/bash
sudo journalctl -u btc-paper-trader -f --no-pager
EOF

chmod +x "$BOT_DIR/start.sh" "$BOT_DIR/stop.sh" "$BOT_DIR/status.sh" "$BOT_DIR/logs.sh"

echo ""
echo "=========================================="
echo "  SETUP COMPLETE!"
echo "=========================================="
echo ""
echo "  Commands:"
echo "    ./start.sh   - Start the bot"
echo "    ./stop.sh    - Stop the bot"
echo "    ./status.sh  - See trade stats"
echo "    ./logs.sh    - Watch live logs"
echo ""
echo "  Run ./start.sh to begin paper trading!"
echo ""
