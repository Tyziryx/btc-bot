#!/bin/bash
# fetch-server-data.sh
# Récupère toutes les données de trading du serveur avant qu'un deploy les efface.
# Usage : bash fetch-server-data.sh
#         bash fetch-server-data.sh --pre-deploy   (appelé automatiquement par deploy.sh)

set -e

SERVER="root@217.154.8.243"
REMOTE_BOT="/root/bot"
LOCAL_HISTORY="data/history"
PRE_DEPLOY=false

[[ "$1" == "--pre-deploy" ]] && PRE_DEPLOY=true

# ── Timestamp de la session ───────────────────────────────────────────────────
SESSION_TS=$(date -u +"%Y%m%d_%H%M%S")
SESSION_DIR="$LOCAL_HISTORY/$SESSION_TS"
mkdir -p "$SESSION_DIR/logs"

echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║          FETCH SERVER DATA — $SESSION_TS          ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""

# ── 1. Trades JSONL ───────────────────────────────────────────────────────────
echo "[1/4] Récupération des trades..."

REMOTE_TRADES="$REMOTE_BOT/data/arb_trades.jsonl"
LOCAL_TRADES="$SESSION_DIR/arb_trades.jsonl"

if ssh -o ConnectTimeout=10 -o BatchMode=yes "$SERVER" "test -s $REMOTE_TRADES" 2>/dev/null; then
    scp -q "$SERVER:$REMOTE_TRADES" "$LOCAL_TRADES"
    TRADE_COUNT=$(wc -l < "$LOCAL_TRADES" | tr -d ' ')
    echo "  ✓ arb_trades.jsonl — $TRADE_COUNT trades"
else
    echo "  ✗ Aucun trade sur le serveur (fichier vide ou absent)"
    touch "$LOCAL_TRADES"
    TRADE_COUNT=0
fi

# ── 2. Logs ───────────────────────────────────────────────────────────────────
echo "[2/4] Récupération des logs..."

LOG_COUNT=$(ssh -o ConnectTimeout=10 "$SERVER" \
    "ls $REMOTE_BOT/data/logs/arb_*.log $REMOTE_BOT/data/logs/bot_*.log 2>/dev/null | wc -l")

if [[ "$LOG_COUNT" -gt 0 ]]; then
    scp -q "$SERVER:$REMOTE_BOT/data/logs/arb_*.log" "$SESSION_DIR/logs/" 2>/dev/null || true
    scp -q "$SERVER:$REMOTE_BOT/data/logs/bot_*.log" "$SESSION_DIR/logs/" 2>/dev/null || true
    COPIED_LOGS=$(ls "$SESSION_DIR/logs/" 2>/dev/null | wc -l | tr -d ' ')
    echo "  ✓ $COPIED_LOGS fichier(s) de logs copiés"
else
    echo "  ✗ Aucun log sur le serveur"
    COPIED_LOGS=0
fi

# ── 3. Merge JSONL global ─────────────────────────────────────────────────────
echo "[3/4] Fusion dans l'historique global..."

GLOBAL_TRADES="$LOCAL_HISTORY/all_trades.jsonl"

if [[ "$TRADE_COUNT" -gt 0 ]]; then
    # Éviter les doublons : ne garder que les lignes pas encore dans all_trades.jsonl
    if [[ -f "$GLOBAL_TRADES" ]]; then
        # Clé de déduplication = window_id + timestamp + status
        NEW_LINES=$(comm -23 \
            <(sort "$LOCAL_TRADES") \
            <(sort "$GLOBAL_TRADES") 2>/dev/null || cat "$LOCAL_TRADES")
        ADDED=$(echo "$NEW_LINES" | grep -c '{' 2>/dev/null || echo 0)
        echo "$NEW_LINES" >> "$GLOBAL_TRADES"
        # Re-trier par timestamp
        sort -t'"' -k4 "$GLOBAL_TRADES" -o "$GLOBAL_TRADES" 2>/dev/null || true
    else
        cp "$LOCAL_TRADES" "$GLOBAL_TRADES"
        ADDED=$TRADE_COUNT
    fi
    TOTAL=$(wc -l < "$GLOBAL_TRADES" | tr -d ' ')
    echo "  ✓ +$ADDED nouveaux trades → total historique : $TOTAL trades"
else
    TOTAL=$(wc -l < "$GLOBAL_TRADES" 2>/dev/null | tr -d ' ' || echo 0)
    echo "  → Historique inchangé : $TOTAL trades"
fi

# ── 4. Résumé financier rapide ────────────────────────────────────────────────
echo "[4/4] Résumé de la session récupérée..."

if [[ "$TRADE_COUNT" -gt 0 && -f "$LOCAL_TRADES" ]]; then
    python3 - "$LOCAL_TRADES" << 'PYEOF'
import json, sys
from collections import Counter

path = sys.argv[1]
trades = []
with open(path) as f:
    for line in f:
        line = line.strip()
        if line:
            try:
                trades.append(json.loads(line))
            except Exception:
                pass

if not trades:
    print("  (aucun trade valide)")
    sys.exit(0)

statuses = Counter(t.get("status","?") for t in trades)
profits  = [t.get("profit", 0) for t in trades]
total_pnl = sum(profits)
wins  = statuses.get("win", 0) + statuses.get("complete", 0)
loses = statuses.get("lose", 0)
abds  = statuses.get("abandoned", 0)
decided = wins + loses
wr = wins/decided*100 if decided else 0

cap_vals = [t.get("capital_after") for t in trades if t.get("capital_after")]
cap_start = min(cap_vals) if cap_vals else "?"
cap_end   = max(cap_vals) if cap_vals else "?"

print(f"  Trades    : {len(trades)} total  ({wins}W / {loses}L / {abds}ABD)")
print(f"  Win rate  : {wr:.1f}%  ({decided} résolus)")
print(f"  PnL total : {'%+.4f' % total_pnl} €")
print(f"  Capital   : {cap_start:.2f} → {cap_end:.2f} €" if isinstance(cap_start, float) else f"  Capital   : {cap_start} → {cap_end}")
if profits:
    avg_w = sum(p for p in profits if p > 0) / max(wins, 1)
    avg_l = sum(p for p in profits if p < 0) / max(loses + abds, 1)
    print(f"  Avg win   : +{avg_w:.4f} €  |  Avg loss : {avg_l:.4f} €")
PYEOF
else
    echo "  (pas de trades à résumer)"
fi

# ── Sauvegarde d'un manifest ──────────────────────────────────────────────────
cat > "$SESSION_DIR/manifest.json" << MANIFEST
{
  "session_ts": "$SESSION_TS",
  "pre_deploy": $PRE_DEPLOY,
  "trades_count": $TRADE_COUNT,
  "logs_count": $COPIED_LOGS,
  "server": "$SERVER"
}
MANIFEST

echo ""
echo "──────────────────────────────────────────────────────"
echo "  Sauvegardé dans : $SESSION_DIR"
echo "  Historique global : $GLOBAL_TRADES"
if [[ "$PRE_DEPLOY" == true ]]; then
    echo "  ⚡ Mode pré-deploy : deploy.sh peut maintenant nettoyer sans risque"
fi
echo "──────────────────────────────────────────────────────"
echo ""
