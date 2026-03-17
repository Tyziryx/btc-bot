#!/bin/bash
# Live logs (follows journald)
# Usage:
#   ./logs.sh          - live stream (Ctrl+C to stop)
#   ./logs.sh history  - list all saved log files
#   ./logs.sh read     - read the latest saved log file
#   ./logs.sh read N   - read the Nth most recent log file

cd "$(dirname "$0")"

case "${1:-}" in
    history)
        echo ""
        echo "  SAVED LOG FILES (data/logs/)"
        echo "  =========================================="
        if ls data/logs/bot_*.log 1>/dev/null 2>&1; then
            ls -lht data/logs/bot_*.log | awk '{print "  " $6, $7, $8, $9, "(" $5 ")"}'
        else
            echo "  No log files yet."
        fi
        echo ""
        ;;
    read)
        N=${2:-1}
        FILE=$(ls -t data/logs/bot_*.log 2>/dev/null | sed -n "${N}p")
        if [ -z "$FILE" ]; then
            echo "No log file found (index $N)"
            exit 1
        fi
        echo "=== $FILE ==="
        cat "$FILE"
        ;;
    *)
        sudo journalctl -u btc-bot -f --no-pager
        ;;
esac
