#!/bin/bash
# Starts: FastAPI backend + Next.js frontend + ngrok tunnel

set -e
cd "$(dirname "$0")"

echo "=== Starting BTC Bot Dashboard ==="

# 1. Install Python deps if needed
if [ ! -d "api/.venv" ]; then
    echo "[1/4] Creating Python venv..."
    python3 -m venv api/.venv
    api/.venv/bin/pip install -r api/requirements.txt
else
    echo "[1/4] Python venv OK"
fi

# 2. Install Node deps if needed
if [ ! -d "web/node_modules" ]; then
    echo "[2/4] Installing Node deps..."
    cd web && npm install && cd ..
else
    echo "[2/4] Node deps OK"
fi

# 3. Build Next.js
echo "[3/4] Building Next.js..."
cd web && npm run build && cd ..

# 4. Start everything
echo "[4/4] Starting services..."

# FastAPI (port 8888)
api/.venv/bin/uvicorn dashboard.api.main:app --host 0.0.0.0 --port 8888 &
echo "  API:  http://localhost:8888"

# Next.js (port 3000)
cd web && npm start &
echo "  Web:  http://localhost:3000"
cd ..

# ngrok (tunnel to Next.js)
if command -v ngrok &> /dev/null; then
    ngrok http 3000 --log=stdout > /tmp/ngrok.log &
    sleep 3
    NGROK_URL=$(curl -s http://localhost:4040/api/tunnels | python3 -c "import sys,json; print(json.load(sys.stdin)['tunnels'][0]['public_url'])" 2>/dev/null || echo "ngrok starting...")
    echo "  ngrok: $NGROK_URL"
else
    echo "  ngrok not installed. Run: snap install ngrok"
    echo "  Then: ngrok config add-authtoken YOUR_TOKEN"
fi

echo ""
echo "=== Dashboard running! ==="
echo "  Local:  http://localhost:3000"
echo "  Stop:   ./stop-dashboard.sh"

wait
