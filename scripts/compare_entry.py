"""对比：回踩就买 vs 企稳确认，同一批信号的胜率/盈亏比/期望收益"""
import sys
sys.path.insert(0, "/www/wwwroot/epro")
from collections import defaultdict
from src.combo.combination_miner import (
    load_trade_dates, split_train_test, load_tradable_codes,
    is_market_bull, _find_pullback_entry, _find_entry,
)
from src.factor.factor_library import load_klines
from src.db.connection import get_connection
from src.strategy.base_strategy import to_date

TARGET = {'limit_up', 'macd_golden', 'second_breakout'}
HOLD_DAYS = 60
STOP_PCT = 0.08

conn = get_connection()
cursor = conn.cursor()
dates = load_trade_dates()
train_dates, test_dates = split_train_test(dates)
codes = load_tradable_codes()

bull_map = {}
cursor.execute("SELECT code, t, c, ma20 FROM index_kline")
for r in cursor.fetchall():
    bull_map.setdefault(r['code'], {})[to_date(r['t'])] = (float(r['c']) if r['c'] is not None else None, float(r['ma20']) if r['ma20'] is not None else None)

def simulate(klines, ei, ep):
    if ei + HOLD_DAYS >= len(klines):
        return None
    stop = ep * (1 - STOP_PCT)
    for j in range(ei + 1, ei + HOLD_DAYS + 1):
        low = klines[j]['l']
        if low is not None and float(low) <= stop:
            return (stop - ep) / ep * 100
    return (float(klines[ei + HOLD_DAYS]['c']) - ep) / ep * 100

rets_old = []  # 回踩就买
rets_new = []  # 企稳确认

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
        # 旧：回踩就买（返回下标，买入价=回踩日收盘）
        pb = _find_pullback_entry(klines, si)
        if pb is not None:
            ep = float(klines[pb]['c'])
            r = simulate(klines, pb, ep)
            if r is not None:
                rets_old.append(r)
        # 新：企稳确认
        en = _find_entry(klines, si)
        if en is not None:
            r = simulate(klines, en[0], en[1])
            if r is not None:
                rets_new.append(r)

def stats(xs, label):
    if not xs:
        print(f"{label}: 无样本")
        return
    wins = [x for x in xs if x > 0]
    losses = [x for x in xs if x <= 0]
    wr = 100 * len(wins) / len(xs)
    aw = sum(wins)/len(wins) if wins else 0
    al = sum(losses)/len(losses) if losses else 0
    ratio = aw / abs(al) if al else 0
    exp = (wr/100)*aw - (1-wr/100)*abs(al)
    print(f"{label}: 样本{len(xs)} 胜率{wr:.1f}% 均盈{aw:.1f}% 均亏{al:.1f}% 盈亏比{ratio:.2f} 期望{exp:.2f}%")

print(f"组合 limit_up+macd_golden+second_breakout 中60日（测试期）")
print()
stats(rets_old, "回踩就买")
stats(rets_new, "企稳确认")

conn.close()
