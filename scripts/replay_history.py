"""历史回放：用最优组合输出具体选股记录（股票+买入价+止损+收益）"""
import sys
sys.path.insert(0, "/www/wwwroot/epro")
from collections import defaultdict
from src.combo.combination_miner import (
    load_trade_dates, split_train_test, load_tradable_codes,
    is_market_bull, _find_pullback_entry, PERIODS,
)
from src.factor.factor_library import load_klines
from src.db.connection import get_connection
from src.strategy.base_strategy import to_date

# 最优组合：limit_up + macd_golden + second_breakout，中60日
TARGET = {'limit_up', 'macd_golden', 'second_breakout'}
HOLD_DAYS = 60
STOP_PCT = 0.08

conn = get_connection()
cursor = conn.cursor()

dates = load_trade_dates()
train_dates, test_dates = split_train_test(dates)
codes = load_tradable_codes()

# 预加载指数
bull_map = {}
cursor.execute("SELECT code, t, c, ma20 FROM index_kline")
for r in cursor.fetchall():
    bull_map.setdefault(r['code'], {})[to_date(r['t'])] = (float(r['c']) if r['c'] is not None else None, float(r['ma20']) if r['ma20'] is not None else None)

# 预加载股票名称
name_map = {}
cursor.execute("SELECT dm, mc FROM stock_basic")
for r in cursor.fetchall():
    name_map[r['dm']] = r['mc']

records = []
for dm in codes:
    cursor.execute("SELECT t, factor FROM factor_flag WHERE dm=%s AND flag=1 AND factor IN ('limit_up','macd_golden','second_breakout')", (dm,))
    flags = defaultdict(set)
    for r in cursor.fetchall():
        flags[to_date(r['t'])].add(r['factor'])
    if not flags:
        continue
    klines = load_klines(dm, cursor)
    idx = {b['t']: i for i, b in enumerate(klines) if b['t'] is not None}
    for day, fs in flags.items():
        if not TARGET.issubset(fs):
            continue
        if day not in test_dates:  # 只看测试期（近期）
            continue
        if not is_market_bull(dm, day, bull_map):
            continue
        si = idx.get(day)
        if si is None:
            continue
        pb = _find_pullback_entry(klines, si)
        if pb is None:
            continue
        ei, ep = pb
        if ei + HOLD_DAYS >= len(klines):
            continue
        # 模拟持有
        stop = ep * (1 - STOP_PCT)
        exit_price = None
        for j in range(ei + 1, ei + HOLD_DAYS + 1):
            low = klines[j]['l']
            if low is not None and float(low) <= stop:
                exit_price = stop
                break
        if exit_price is None:
            exit_price = float(klines[ei + HOLD_DAYS]['c'])
        ret = (exit_price - ep) / ep * 100
        records.append({
            'buy_date': klines[ei]['t'],
            'dm': dm,
            'mc': name_map.get(dm, ''),
            'entry': ep,
            'stop': stop,
            'exit': exit_price,
            'ret': ret,
        })

# 按买入日期倒序，取最近30条
records.sort(key=lambda r: str(r['buy_date']), reverse=True)
print(f"最优组合 limit_up+macd_golden+second_breakout 中60日，测试期共 {len(records)} 笔交易")
print()
print(f"{'买入日':<12}{'代码':<8}{'名称':<10}{'买入价':>8}{'止损价':>8}{'出场价':>8}{'收益':>8}")
print("-" * 70)
for r in records[:30]:
    flag = "✅" if r['ret'] > 0 else "❌"
    print(f"{str(r['buy_date']):<12}{r['dm']:<8}{r['mc']:<10}{r['entry']:>8.2f}{r['stop']:>8.2f}{r['exit']:>8.2f}{r['ret']:>+7.1f}% {flag}")

# 统计
if records:
    wins = [r for r in records if r['ret'] > 0]
    losses = [r for r in records if r['ret'] <= 0]
    print("-" * 70)
    print(f"总交易 {len(records)} 笔，盈利 {len(wins)} 笔，胜率 {100*len(wins)/len(records):.1f}%")
    print(f"平均盈利 {sum(r['ret'] for r in wins)/len(wins):.2f}%，平均亏损 {sum(r['ret'] for r in losses)/len(losses):.2f}%")

conn.close()
