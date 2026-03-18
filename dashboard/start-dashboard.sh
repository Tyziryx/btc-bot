#!/bin/bash
# Starts: FastAPI backend + Next.js standalone + ngrok tunnel

set -e
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

# 2. Find standalone server.js (path varies between Windows/Linux builds)
SERVER_JS=$(find web/.next/standalone -maxdepth 6 -name "server.js" ! -path "*/node_modules/*" 2>/dev/null | head -1)
if [ -z "$SERVER_JS" ]; then
    echo "ERROR: standalone build not found. Build locally and push."
    exit 1
fi
STANDALONE_DIR=$(dirname "$SERVER_JS")
echo "[2/3] Standalone build OK: $STANDALONE_DIR"

# 3. Copy static files to standalone (required by Next.js standalone)
cp -r web/public "$STANDALONE_DIR/public" 2>/dev/null || true
mkdir -p "$STANDALONE_DIR/.next"
cp -r web/.next/static "$STANDALONE_DIR/.next/static" 2>/dev/null || true

echo "[3/3] Starting services..."

# FastAPI (port 8888) - run from project root so data/ paths resolve
cd ..
dashboard/api/.venv/bin/uvicorn dashboard.api.main:app --host 0.0.0.0 --port 8888 &
echo "  API:  http://localhost:8888"

# Next.js standalone (port 3000)
cd "dashboard/$STANDALONE_DIR"
PORT=3000 HOSTNAME=0.0.0.0 node server.js &
echo "  Web:  http://localhost:3000"
cd /root/bot/dashboard

# ngrok (tunnel to Next.js)
if command -v ngrok &> /dev/null; then
    ngrok http 3000 --log=stdout > /tmp/ngrok.log &
    sleep 3
    NGROK_URL=$(curl -s http://localhost:4040/api/tunnels | python3 -c "import sys,json; print(json.load(sys.stdin)['tunnels'][0]['public_url'])" 2>/dev/null || echo "ngrok starting...")
    echo "  ngrok: $NGROK_URL"
else
    echo "  ngrok not installed. Run: snap install ngrok"
fi

echo ""
echo "=== Dashboard running! ==="
echo "  Stop: ./dashboard/stop-dashboard.sh"

wait
