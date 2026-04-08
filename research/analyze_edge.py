"""
Deep edge analysis for the arb bot.
Finds which conditions lead to completion vs abandonment.
"""
import json
from pathlib import Path
from collections import defaultdict
import statistics
from datetime import datetime

# Load all arb trades, deduplicate by window_id (keep latest record)
all_arb = []
for f in sorted(Path('data/history').glob('*/arb_trades.jsonl')):
    with open(f) as fp:
        for line in fp:
            if line.strip():
                try:
                    all_arb.append(json.loads(line))
                except Exception:
                    pass

seen = {}
for t in all_arb:
    seen[t['window_id']] = t
trades = list(seen.values())

complete = [t for t in trades if t['status'].lower() == 'complete']
abandoned = [t for t in trades if t['status'].lower() == 'abandoned']

print(f'=== ARB EDGE ANALYSIS ===')
print(f'Unique windows: {len(trades)}, Complete: {len(complete)}, Abandoned: {len(abandoned)}')
print(f'Completion rate: {len(complete)/len(trades):.1%}')

# Capital tracking
def get_ts(t):
    try:
        return datetime.fromisoformat(t['timestamp'])
    except Exception:
        return datetime.min

timeline = sorted([t for t in trades if t.get('capital_after')], key=get_ts)
if timeline:
    first_cap = timeline[0].get('capital_after', 0)
    last_cap = timeline[-1].get('capital_after', 0)
    print(f'\n=== CAPITAL TRACKING ===')
    print(f'First recorded capital: {first_cap:.2f}')
    print(f'Last recorded capital: {last_cap:.2f}')
    print(f'Net change: {last_cap - first_cap:+.2f}')

# COMPLETION BY HOUR
print('\n=== COMPLETION BY HOUR (UTC) ===')
hourly = defaultdict(lambda: {'c': 0, 'a': 0, 'profit': 0.0})
for t in trades:
    try:
        ts = datetime.fromisoformat(t['timestamp'])
        h = ts.hour
        status = t['status'].lower()
        profit = t.get('profit', 0) if status == 'complete' else -t.get('bet_size', 2.0)
        key = 'c' if status == 'complete' else 'a'
        hourly[h][key] += 1
        hourly[h]['profit'] += profit
    except Exception:
        pass

bad_hours = []
good_hours = []
for h in range(24):
    d = hourly[h]
    total = d['c'] + d['a']
    if total < 3:
        continue
    rate = d['c'] / total
    flag = ''
    if rate < 0.45:
        flag = ' BAD'
        bad_hours.append(h)
    elif rate > 0.60:
        flag = ' GOOD'
        good_hours.append(h)
    net = d['profit']
    print(f'{h:02d}h: {rate:.0%} ({d["c"]}/{total}) net:{net:+.1f}{flag}')

print(f'BAD hours (<45%): {bad_hours}')
print(f'GOOD hours (>60%): {good_hours}')

# COMPLETION BY ENTRY PRICE
print('\n=== COMPLETION BY ENTRY PRICE ===')
price_buckets = defaultdict(lambda: {'c': 0, 'a': 0, 'profit': 0.0})
for t in trades:
    p = round(t.get('entry_price', 0) / 0.05) * 0.05
    status = t['status'].lower()
    profit = t.get('profit', 0) if status == 'complete' else -t.get('bet_size', 2.0)
    key = 'c' if status == 'complete' else 'a'
    price_buckets[p][key] += 1
    price_buckets[p]['profit'] += profit

for p in sorted(price_buckets.keys()):
    d = price_buckets[p]
    total = d['c'] + d['a']
    if total < 2:
        continue
    rate = d['c'] / total
    flag = ' *** PROFITABLE' if d['profit'] > 0 else ''
    print(f'  entry {p:.2f}: {rate:.0%} ({d["c"]}/{total}), net: {d["profit"]:+.2f}{flag}')

# COMPLETION BY COMBINED COST
print('\n=== COMPLETION BY COMBINED COST ===')
cost_buckets = defaultdict(lambda: {'c': 0, 'a': 0, 'profit': 0.0})
for t in trades:
    c = t.get('combined_cost') or 0.0
    bucket = round(c / 0.02) * 0.02
    status = t['status'].lower()
    profit = t.get('profit', 0) if status == 'complete' else -t.get('bet_size', 2.0)
    key = 'c' if status == 'complete' else 'a'
    cost_buckets[bucket][key] += 1
    cost_buckets[bucket]['profit'] += profit

for b in sorted(cost_buckets.keys()):
    d = cost_buckets[b]
    total = d['c'] + d['a']
    if total < 2:
        continue
    rate = d['c'] / total
    flag = ' ***' if d['profit'] > 0 else ''
    print(f'  combined {b:.2f}: {rate:.0%} ({d["c"]}/{total}), net: {d["profit"]:+.2f}{flag}')

# COMPLETION BY WINDOW REMAINING AT ENTRY
print('\n=== COMPLETION BY WINDOW REMAINING AT ENTRY ===')
remain_buckets = defaultdict(lambda: {'c': 0, 'a': 0, 'profit': 0.0})
for t in trades:
    r = t.get('window_remain_at_entry', 0) or 0
    bucket = (int(r) // 120) * 120
    status = t['status'].lower()
    profit = t.get('profit', 0) if status == 'complete' else -t.get('bet_size', 2.0)
    key = 'c' if status == 'complete' else 'a'
    remain_buckets[bucket][key] += 1
    remain_buckets[bucket]['profit'] += profit

for b in sorted(remain_buckets.keys()):
    d = remain_buckets[b]
    total = d['c'] + d['a']
    if total < 2:
        continue
    rate = d['c'] / total
    mins = b // 60
    print(f'  {mins}m+ remaining: {rate:.0%} ({d["c"]}/{total}), net: {d["profit"]:+.2f}')

# ABANDON REASONS BREAKDOWN
print('\n=== ABANDON REASONS ===')
reason_types = defaultdict(lambda: {'count': 0, 'total_loss': 0.0})
for t in abandoned:
    reason = t.get('abandon_reason', 'unknown')
    rtype = 'price_stop' if 'price_stop' in reason else ('ofi_stop' if 'ofi' in reason else 'timeout')
    reason_types[rtype]['count'] += 1
    reason_types[rtype]['total_loss'] += t.get('bet_size', 2.0)

for rt, d in reason_types.items():
    print(f'  {rt}: {d["count"]} trades, loss: -{d["total_loss"]:.2f}')

# PRICE STOP LOSS ANALYSIS
print('\n=== PRICE STOP LOSS DROPS ===')
drops = []
for t in abandoned:
    reason = t.get('abandon_reason', '')
    if 'price_stop' in reason:
        try:
            bid = float(reason.split('bid=')[1].split(' ')[0])
            entry = float(reason.split('entry=')[1].split(' ')[0])
            drop = 1 - bid/entry
            drops.append(drop)
        except Exception:
            pass

if drops:
    print(f'  Count: {len(drops)}, Mean drop: {statistics.mean(drops):.1%}')
    print(f'  Min drop: {min(drops):.1%}, Max drop: {max(drops):.1%}')
    # Distribution
    hist = defaultdict(int)
    for d in drops:
        bucket = round(d / 0.05) * 0.05
        hist[bucket] += 1
    for k in sorted(hist.keys()):
        print(f'    {k:.0%}: {hist[k]} trades')

# COMPLETE TRADE PROFIT DISTRIBUTION
print('\n=== COMPLETE TRADE PROFIT DISTRIBUTION ===')
profits = sorted(t.get('profit', 0) for t in complete)
if profits:
    print(f'Mean: {statistics.mean(profits):.3f}, Median: {statistics.median(profits):.3f}')
    print(f'Min: {min(profits):.3f}, Max: {max(profits):.3f}')
    print(f'Total: {sum(profits):.2f} over {len(profits)} trades')

# COMBINED COST vs PROFIT for complete trades
print('\n=== COMBINED COST → EXPECTED PROFIT (complete only) ===')
for t in sorted(complete, key=lambda x: x.get('combined_cost', 0))[:5]:
    cc = t.get('combined_cost', 0)
    ep = t.get('entry_price', 0)
    l2 = t.get('leg2_price', 0)
    shares = t.get('shares', 0)
    profit = t.get('profit', 0)
    print(f'  entry={ep} leg2={l2} combined={cc} shares={shares:.2f} → profit={profit:.3f}')

# SIMULATE: What if we only enter with combined < X?
print('\n=== SIMULATION: FILTER BY COMBINED_AT_ENTRY ===')
for threshold in [0.80, 0.82, 0.84, 0.86, 0.88, 0.90, 0.92, 0.94, 0.96]:
    filtered = [t for t in trades if (t.get('combined_cost') or 0) <= threshold]
    f_complete = [t for t in filtered if t['status'].lower() == 'complete']
    f_abandoned = [t for t in filtered if t['status'].lower() == 'abandoned']
    if not filtered:
        continue
    cr = len(f_complete) / len(filtered)
    pnl = sum(t.get('profit', 0) for t in f_complete) - len(f_abandoned) * 2.0
    print(f'  combined <= {threshold}: {len(filtered)} trades, CR={cr:.0%}, PnL={pnl:+.2f}')
