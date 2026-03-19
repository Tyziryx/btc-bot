#!/bin/bash
# Starts: FastAPI backend + Next.js standalone + ngrok tunnel
# All processes run in background, script returns immediately.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "=== Starting BTC Bot Dashboard ==="

# 0. Kill any existing processes
fuser -k 3000/tcp 2>/dev/null || true
fuser -k 8888/tcp 2>/dev/null || true
pkill -f ngrok 2>/dev/null || true
sleep 1

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

# 3. Ensure static files are in standalone (critical for CSS/JS)
mkdir -p "$STANDALONE_DIR/.next"
if [ ! -d "$STANDALONE_DIR/.next/static" ]; then
    echo "  Copying static files to standalone..."
    cp -r web/.next/static "$STANDALONE_DIR/.next/static"
fi
# Always sync to catch updates
cp -r web/.next/static/* "$STANDALONE_DIR/.next/static/" 2>/dev/null || true
# Copy public dir too
cp -r web/public "$STANDALONE_DIR/public" 2>/dev/null || true

echo "[3/3] Starting services..."

# FastAPI (port 8888) - run from project root
cd "$SCRIPT_DIR/.."
nohup "$SCRIPT_DIR/api/.venv/bin/uvicorn" dashboard.api.main:app --host 0.0.0.0 --port 8888 > /tmp/dashboard-api.log 2>&1 &
echo "  API:  http://localhost:8888 (PID $!)"

# Next.js standalone (port 3000)
cd "$SCRIPT_DIR/$STANDALONE_DIR"
PORT=3000 HOSTNAME=0.0.0.0 nohup node server.js > /tmp/dashboard-web.log 2>&1 &
echo "  Web:  http://localhost:3000 (PID $!)"

# ngrok tunnel
cd "$SCRIPT_DIR"
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
