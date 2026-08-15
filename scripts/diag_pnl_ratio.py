"""诊断：计算样本大组合的盈亏比和期望收益（决定A方案可行性）"""
import sys
sys.path.insert(0, "/www/wwwroot/epro")
from src.combo.combination_miner import (
    mine, load_trade_dates, split_train_test, load_tradable_codes,
    is_market_bull, _find_pullback_entry, _simulate_periods, PERIODS,
)
from src.factor.factor_library import load_klines, FACTOR_NAMES
from src.db.connection import get_connection
from src.strategy.base_strategy import to_date
from collections import defaultdict

# 聚焦：ma_bull + shrink_pullback 短5日 的收益分布
conn = get_connection()
cursor = conn.cursor()

dates = load_trade_dates()
train_dates, test_dates = split_train_test(dates)
codes = load_tradable_codes()

# 预加载指数 ma20
bull_map = {}
cursor.execute("SELECT code, t, c, ma20 FROM index_kline")
for r in cursor.fetchall():
    bull_map.setdefault(r['code'], {})[to_date(r['t'])] = (float(r['c']) if r['c'] is not None else None, float(r['ma20']) if r['ma20'] is not None else None)

rets_train, rets_test = [], []
target_factors = {'ma_bull', 'shrink_pullback'}

count = 0
for dm in codes:
    cursor.execute("SELECT t, factor FROM factor_flag WHERE dm=%s AND flag=1 AND factor IN ('ma_bull','shrink_pullback')", (dm,))
    flags = defaultdict(set)
    for r in cursor.fetchall():
        flags[to_date(r['t'])].add(r['factor'])
    klines = load_klines(dm, cursor)
    idx = {b['t']: i for i, b in enumerate(klines) if b['t'] is not None}
    for day, fs in flags.items():
        if not target_factors.issubset(fs):
            continue
        if day not in train_dates and day not in test_dates:
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
        rr = _simulate_periods(klines, ei, ep)
        # 短5日 = PERIODS[1] 的 period
        for spec in PERIODS:
            if spec.period == "短":
                ret = rr.get(spec.period)
                if ret is not None:
                    (rets_train if day in train_dates else rets_test).append(ret)
    count += 1
    if count % 1000 == 0:
        print(f"进度 {count}/{len(codes)} 训练样本={len(rets_train)} 测试样本={len(rets_test)}")

def stats(xs):
    if not xs:
        return None
    wins = [x for x in xs if x > 0]
    losses = [x for x in xs if x <= 0]
    wr = 100 * len(wins) / len(xs)
    avg_win = sum(wins)/len(wins) if wins else 0
    avg_loss = sum(losses)/len(losses) if losses else 0
    ratio = (avg_win / abs(avg_loss)) if avg_loss else 0
    exp = (wr/100) * avg_win - (1-wr/100) * abs(avg_loss)
    return f"胜率{wr:.1f}% 均盈{avg_win:.2f}% 均亏{avg_loss:.2f}% 盈亏比{ratio:.2f} 期望收益{exp:.2f}%"

print()
print(f"ma_bull+shrink_pullback 短5日：")
print(f"  训练期({len(rets_train)}样本): {stats(rets_train)}")
print(f"  测试期({len(rets_test)}样本): {stats(rets_test)}")

conn.close()
