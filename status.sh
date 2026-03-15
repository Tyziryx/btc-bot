#!/bin/bash
cd "$(dirname "$0")"

echo ""
echo "=========================================================="
echo "  BTC PAPER TRADER V2 PRO - STATUS"
echo "=========================================================="

# Service status
STATE=$(systemctl is-active btc-bot 2>/dev/null)
if [ "$STATE" = "active" ]; then
    UPTIME=$(systemctl show btc-bot --property=ActiveEnterTimestamp --value 2>/dev/null)
    echo "  Service:    RUNNING since $UPTIME"
else
    echo "  Service:    STOPPED"
fi
echo ""

# Trade stats
if [ -f data/paper_trades.json ]; then
    python3 -c "
import json, sys
with open('data/paper_trades.json') as f:
    trades = json.load(f)

if not trades:
    print('  No trades yet.')
    sys.exit()

wins = [t for t in trades if t['won']]
losses = [t for t in trades if not t['won']]
total_pnl = sum(t['pnl'] for t in trades)
capital = trades[-1]['capital_after']
start_capital = trades[0]['capital_before']
roi = (capital / start_capital - 1) * 100
wr = len(wins) / len(trades) * 100

# Peak and drawdown
peak = start_capital
max_dd = 0
for t in trades:
    peak = max(peak, t['capital_after'])
    dd = (peak - t['capital_after']) / peak * 100
    max_dd = max(max_dd, dd)

avg_win = sum(t['pnl'] for t in wins) / len(wins) if wins else 0
avg_loss = sum(t['pnl'] for t in losses) / len(losses) if losses else 0

# Polymarket price stats
real_prices = [t for t in trades if t.get('entry_price', 0) != 0.52]
fake_prices = len(trades) - len(real_prices)

print('  PERFORMANCE')
print('  ----------------------------------------------------------')
print('  Capital:      \$%.2f  (started \$%.2f)' % (capital, start_capital))
print('  ROI:          %+.1f%%' % roi)
print('  Total PnL:    %s\$%.2f' % ('+' if total_pnl >= 0 else '-', abs(total_pnl)))
print('  Max Drawdown: %.1f%%' % max_dd)
print()
print('  TRADES')
print('  ----------------------------------------------------------')
print('  Total:        %d  |  Wins: %d  |  Losses: %d' % (len(trades), len(wins), len(losses)))
print('  Win Rate:     %.1f%%' % wr)
print('  Avg Win:      +\$%.2f' % avg_win)
print('  Avg Loss:     -\$%.2f' % abs(avg_loss))
if losses:
    pf = (avg_win * len(wins)) / (abs(avg_loss) * len(losses))
    print('  Profit Factor: %.2f' % pf)
print('  Real Prices:  %d/%d trades (%.0f%%)' % (len(real_prices), len(trades), len(real_prices)/len(trades)*100))
print()
print('  TIMELINE')
print('  ----------------------------------------------------------')
print('  First trade:  %s' % trades[0]['timestamp'][:19])
print('  Last trade:   %s' % trades[-1]['timestamp'][:19])

# Hourly breakdown
from collections import defaultdict
hours = defaultdict(lambda: {'w': 0, 'l': 0, 'pnl': 0})
for t in trades:
    h = t['timestamp'][11:13]
    if t['won']:
        hours[h]['w'] += 1
    else:
        hours[h]['l'] += 1
    hours[h]['pnl'] += t['pnl']

print()
print('  LAST 10 TRADES')
print('  ----------------------------------------------------------')
for t in trades[-10:]:
    icon = '+' if t['won'] else 'X'
    status = 'WIN ' if t['won'] else 'LOSS'
    ts = t['timestamp'][11:19]
    print('  %s %s %s %-4s entry=\$%.2f bet=\$%.2f pnl=%s\$%.2f cap=\$%.2f' % (
        icon, ts, status, t['direction'],
        t['entry_price'], t['bet_size'],
        '+' if t['pnl'] >= 0 else '', abs(t['pnl']),
        t['capital_after']))
" 2>/dev/null
else
    echo "  No trades yet - bot is warming up..."
fi

echo ""
echo "=========================================================="
echo "  ./logs.sh = live logs | ./stop.sh = stop | ./start.sh = start"
echo "=========================================================="
echo ""
