"""诊断：对比不同止损幅度的胜率、盈亏比、期望收益"""
import sys
sys.path.insert(0, "/www/wwwroot/epro")
from collections import defaultdict
from src.combo.combination_miner import (
    load_trade_dates, split_train_test, load_tradable_codes,
    is_market_bull, _find_pullback_entry,
)
from src.factor.factor_library import load_klines
from src.db.connection import get_connection
from src.strategy.base_strategy import to_date

TARGET = {'limit_up', 'macd_golden', 'second_breakout'}
HOLD_DAYS = 60

conn = get_connection()
cursor = conn.cursor()
dates = load_trade_dates()
train_dates, test_dates = split_train_test(dates)
codes = load_tradable_codes()

bull_map = {}
cursor.execute("SELECT code, t, c, ma20 FROM index_kline")
for r in cursor.fetchall():
    bull_map.setdefault(r['code'], {})[to_date(r['t'])] = (float(r['c']) if r['c'] is not None else None, float(r['ma20']) if r['ma20'] is not None else None)

# 收集所有测试期交易（买入价+后续K线），然后对不同止损计算
trades = []  # (buy_date, entry_price, future_klines)
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
        if day not in test_dates:
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
        future = klines[ei+1 : ei+HOLD_DAYS+1]
        trades.append((ep, future))

print(f"测试期总交易 {len(trades)} 笔，持有{HOLD_DAYS}天")
print()
print(f"{'止损':<8}{'胜率':<8}{'均盈':<8}{'均亏':<8}{'盈亏比':<8}{'期望收益':<10}")
print("-" * 55)
for stop_pct in [0.05, 0.08, 0.10, 0.12, 0.15, 0.20]:
    rets = []
    for ep, future in trades:
        ep = float(ep)
        stop = ep * (1 - stop_pct)
        exit_p = None
        for b in future:
            low = b['l']
            if low is not None and float(low) <= stop:
                exit_p = stop
                break
        if exit_p is None:
            exit_p = float(future[-1]['c'])
        rets.append((exit_p - ep) / ep * 100)
    wins = [x for x in rets if x > 0]
    losses = [x for x in rets if x <= 0]
    wr = 100 * len(wins) / len(rets)
    aw = sum(wins)/len(wins) if wins else 0
    al = sum(losses)/len(losses) if losses else 0
    ratio = aw / abs(al) if al else 0
    exp = (wr/100)*aw - (1-wr/100)*abs(al)
    print(f"{stop_pct*100:.0f}%{'':<4}{wr:.1f}%{'':<3}{aw:.1f}%{'':<3}{al:.1f}%{'':<3}{ratio:.2f}{'':<4}{exp:.2f}%")

conn.close()
