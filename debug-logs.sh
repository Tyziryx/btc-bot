#!/bin/bash
# Dump ALL logs + system state for debugging — run: bash debug-logs.sh

SEP="=========================================="

echo "$SEP"
echo "  DEBUG DUMP — $(date)"
echo "$SEP"

echo ""
echo "### PROCESSES (ngrok / node / uvicorn / btc-arb)"
ps aux | grep -E "ngrok|node|uvicorn|btc-arb|arb_trader" | grep -v grep

echo ""
echo "### PORTS (3000 / 8888 / 4040)"
ss -tlnp | grep -E "3000|8888|4040" || echo "(none listening)"

echo ""
echo "### NGROK CONFIG (/root/ngrok-bot.yml)"
cat /root/ngrok-bot.yml 2>/dev/null || echo "(file not found)"

echo ""
echo "### NGROK SNAP CONFIG"
find /root/snap/ngrok -name "ngrok.yml" 2>/dev/null | while read f; do
    echo "--- $f ---"
    cat "$f"
done

echo ""
echo "### NGROK API (live tunnels)"
curl -s http://localhost:4040/api/tunnels 2>/dev/null | python3 -m json.tool 2>/dev/null || echo "(ngrok API not responding)"

echo ""
echo "### NGROK LOG (last 50 lines)"
tail -50 /tmp/ngrok.log 2>/dev/null || echo "(no ngrok log)"

echo ""
echo "### DASHBOARD API LOG (last 30 lines)"
tail -30 /tmp/dashboard-api.log 2>/dev/null || echo "(no API log)"

echo ""
echo "### DASHBOARD WEB LOG (last 30 lines)"
tail -30 /tmp/dashboard-web.log 2>/dev/null || echo "(no web log)"

echo ""
echo "### ARB BOT LOG (last 50 lines)"
journalctl -u btc-arb -n 50 --no-pager 2>/dev/null || echo "(no systemd log)"

echo ""
echo "### LATEST BOT LOG FILE (last 30 lines)"
LATEST=$(ls -t /root/bot/data/logs/arb_*.log 2>/dev/null | head -1)
if [ -n "$LATEST" ]; then
    echo "(file: $LATEST)"
    tail -30 "$LATEST"
else
    echo "(no arb log file found)"
fi

echo ""
echo "$SEP"
echo "  END OF DEBUG DUMP"
echo "$SEP"
