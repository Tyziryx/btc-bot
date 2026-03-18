#!/bin/bash
# Starts: FastAPI backend + Next.js standalone + ngrok tunnel
# All processes run in background, script returns immediately.

cd "$(dirname "$0")"

echo "=== Starting BTC Bot Dashboard ==="

# 1. Install Python deps if needed
if [ ! -d "api/.venv" ]; then
    echo "[1/3] Creating Python venv..."
    python3 -m venv api/.venv
    api/.venv/bin/pip install -r api/requirements.txt
else
    echo "[1/3] Python venv OK"
fi

# 2. Find standalone server.js
SERVER_JS=$(find web/.next/standalone -maxdepth 6 -name "server.js" ! -path "*/node_modules/*" 2>/dev/null | head -1)
if [ -z "$SERVER_JS" ]; then
    echo "ERROR: standalone build not found. Build locally and push."
    exit 1
fi
STANDALONE_DIR=$(dirname "$SERVER_JS")
echo "[2/3] Standalone build OK: $STANDALONE_DIR"

# 3. Copy static files to standalone
cp -r web/public "$STANDALONE_DIR/public" 2>/dev/null || true
mkdir -p "$STANDALONE_DIR/.next"
cp -r web/.next/static "$STANDALONE_DIR/.next/static" 2>/dev/null || true

echo "[3/3] Starting services..."

# FastAPI (port 8888) - run from project root
cd ..
nohup dashboard/api/.venv/bin/uvicorn dashboard.api.main:app --host 0.0.0.0 --port 8888 > /tmp/dashboard-api.log 2>&1 &
echo "  API:  http://localhost:8888 (PID $!)"

# Next.js standalone (port 3000)
cd "dashboard/$STANDALONE_DIR"
PORT=3000 HOSTNAME=0.0.0.0 nohup node server.js > /tmp/dashboard-web.log 2>&1 &
echo "  Web:  http://localhost:3000 (PID $!)"
cd /root/bot/dashboard

# ngrok tunnel
if command -v ngrok &> /dev/null; then
    nohup ngrok http 3000 --log=stdout > /tmp/ngrok.log 2>&1 &
    sleep 3
    NGROK_URL=$(curl -s http://localhost:4040/api/tunnels | python3 -c "import sys,json; print(json.load(sys.stdin)['tunnels'][0]['public_url'])" 2>/dev/null || echo "ngrok starting...")
    echo "  ngrok: $NGROK_URL"
else
    echo "  ngrok not installed."
fi

echo ""
echo "=== Dashboard running in background! ==="
echo "  Logs: tail -f /tmp/dashboard-api.log /tmp/dashboard-web.log"
echo "  Stop: ./dashboard/stop-dashboard.sh"
