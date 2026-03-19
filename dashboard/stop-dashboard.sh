#!/bin/bash
echo "Stopping dashboard..."
# Kill by port (most reliable)
fuser -k 3000/tcp 2>/dev/null || true
fuser -k 8888/tcp 2>/dev/null || true
# Kill ngrok
pkill -f ngrok 2>/dev/null || true
sleep 1
echo "Dashboard stopped."
