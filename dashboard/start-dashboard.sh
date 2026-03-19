#!/bin/bash
# Starts: FastAPI backend + Next.js standalone + ngrok tunnel
# One command does everything. Cleans up old processes first.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# Auto-chmod all scripts
chmod +x "$SCRIPT_DIR/start-dashboard.sh" "$SCRIPT_DIR/stop-dashboard.sh" 2>/dev/null || true
chmod +x "$SCRIPT_DIR/../start.sh" "$SCRIPT_DIR/../stop.sh" "$SCRIPT_DIR/../status.sh" "$SCRIPT_DIR/../logs.sh" 2>/dev/null || true

echo "=== Starting BTC Bot Dashboard ==="

# 0. Kill ALL existing processes (thorough cleanup)
echo "[0/4] Cleaning up old processes..."
fuser -k 3000/tcp 2>/dev/null || true
fuser -k 8888/tcp 2>/dev/null || true
pkill -9 -f ngrok 2>/dev/null || true
fuser -k 4040/tcp 2>/dev/null || true
sleep 2

# 1. Install Python deps if needed
if [ ! -d "api/.venv" ]; then
    echo "[1/4] Creating Python venv..."
    python3 -m venv api/.venv
    api/.venv/bin/pip install -r api/requirements.txt
else
    echo "[1/4] Python venv OK"
fi

# 2. Find standalone server.js
SERVER_JS=$(find web/.next/standalone -maxdepth 6 -name "server.js" ! -path "*/node_modules/*" 2>/dev/null | head -1)
if [ -z "$SERVER_JS" ]; then
    echo "ERROR: standalone build not found. Build locally and push."
    exit 1
fi
STANDALONE_DIR=$(dirname "$SERVER_JS")
echo "[2/4] Standalone build OK: $STANDALONE_DIR"

# 3. Ensure static files are in standalone (critical for CSS/JS)
mkdir -p "$STANDALONE_DIR/.next"
cp -r web/.next/static "$STANDALONE_DIR/.next/static" 2>/dev/null || true
cp -r web/.next/static/* "$STANDALONE_DIR/.next/static/" 2>/dev/null || true
cp -r web/public "$STANDALONE_DIR/public" 2>/dev/null || true

echo "[3/4] Starting services..."

# FastAPI (port 8888) - run from project root
cd "$SCRIPT_DIR/.."
nohup "$SCRIPT_DIR/api/.venv/bin/uvicorn" dashboard.api.main:app --host 0.0.0.0 --port 8888 > /tmp/dashboard-api.log 2>&1 &
echo "  API:  http://localhost:8888 (PID $!)"

# Next.js standalone (port 3000)
cd "$SCRIPT_DIR/$STANDALONE_DIR"
PORT=3000 HOSTNAME=0.0.0.0 nohup node server.js > /tmp/dashboard-web.log 2>&1 &
echo "  Web:  http://localhost:3000 (PID $!)"

# 4. ngrok tunnel (with retry to get URL)
cd "$SCRIPT_DIR"
if command -v ngrok &> /dev/null; then
    echo "[4/4] Starting ngrok..."
    nohup ngrok http 3000 --log=stdout > /tmp/ngrok.log 2>&1 &

    # Wait for ngrok to be ready (up to 15 seconds)
    NGROK_URL=""
    for i in $(seq 1 15); do
        sleep 1
        NGROK_URL=$(curl -s http://localhost:4040/api/tunnels 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin)['tunnels'][0]['public_url'])" 2>/dev/null)
        if [ -n "$NGROK_URL" ]; then
            break
        fi
    done

    if [ -n "$NGROK_URL" ]; then
        echo ""
        echo "============================================"
        echo "  DASHBOARD URL: $NGROK_URL"
        echo "============================================"
    else
        echo "  ngrok: failed to start (check /tmp/ngrok.log)"
    fi
else
    echo "[4/4] ngrok not installed — skipping tunnel."
fi

echo ""
echo "=== Dashboard running! ==="
echo "  Logs: tail -f /tmp/dashboard-api.log /tmp/dashboard-web.log"
echo "  Stop: ./dashboard/stop-dashboard.sh"
