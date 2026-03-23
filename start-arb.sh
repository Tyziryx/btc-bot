#!/bin/bash
# Start the arb trading bot
cd "$(dirname "$0")"

# Create systemd service if not exists
if [ ! -f /etc/systemd/system/btc-arb.service ]; then
    echo "Creating btc-arb systemd service..."
    sudo tee /etc/systemd/system/btc-arb.service > /dev/null <<SVCEOF
[Unit]
Description=BTC Arb Trading Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=$(pwd)
ExecStart=$(pwd)/venv/bin/python -u scripts/arb_trade.py --duration 0
Restart=always
RestartSec=30
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
SVCEOF
    sudo systemctl daemon-reload
    sudo systemctl enable btc-arb
fi

sudo systemctl restart btc-arb
echo "Arb bot started! Check: journalctl -u btc-arb -f"
