#!/usr/bin/env python3
"""
因子IC监控模块
- 计算每个因子的 IC（信息系数）
- IC = 因子值与下期收益的相关系数
- 输出各因子的 IC均值、IC标准差、IC>0占比、IR
"""
import os
import sys
import pymysql
from datetime import date, timedelta
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DB = {
    'host': '127.0.0.1', 'port': 3306, 'user': 'epro',
    'password': 'nTWTkkhfYxnbEhFp', 'database': 'epro', 'charset': 'utf8mb4',
}


def calc_factor_ic(conn, factor, hold_days=20, lookback_days=120):
    """计算单因子 IC（横截面相关系数）"""
    cur = conn.cursor(pymysql.cursors.DictCursor)

    # 找因子有效区间
    cur.execute("""
        SELECT MIN(t) AS mn, MAX(t) AS mx FROM factor_flag
        WHERE factor = %s AND flag = 1
    """, (factor,))
    r = cur.fetchone()
    mn, mx = r['mn'], r['mx']
    if not mx:
        return None

    start_date = mx - timedelta(days=lookback_days)
    if start_date < mn:
        start_date = mn

    # 一次性 SQL：取所有信号日 + 后续 hold_days 收益
    cur.execute("""
        SELECT ff.t AS signal_date, ff.dm,
               s.c AS start_close, e.c AS end_close
        FROM factor_flag ff
        JOIN daily_kline s ON ff.dm = s.dm AND s.t = ff.t
        JOIN daily_kline e ON ff.dm = e.dm AND e.t = DATE_ADD(ff.t, INTERVAL %s DAY)
        WHERE ff.factor = %s AND ff.flag = 1
          AND ff.t >= %s
    """, (hold_days, factor, start_date))

    rows = cur.fetchall()
    if not rows:
        return None

    # 按日期聚合
    by_date = {}
    for r in rows:
        d = r['signal_date']
        sc, ec = r['start_close'], r['end_close']
        if sc is None or ec is None or sc == 0:
            continue
        ret = (float(ec) - float(sc)) / float(sc)
        by_date.setdefault(d, []).append(ret)

    ic_series = []
    for d, rets in by_date.items():
        if len(rets) < 5:
            continue
        avg_ret = sum(rets) / len(rets)
        ic_series.append((d, avg_ret, len(rets)))

    if not ic_series:
        return None

    ics = [r[1] for r in ic_series]
    ic_mean = sum(ics) / len(ics)
    ic_std = (sum((x - ic_mean) ** 2 for x in ics) / len(ics)) ** 0.5
    ic_ir = ic_mean / ic_std if ic_std > 0 else 0
    ic_pos_pct = sum(1 for x in ics if x > 0) / len(ics)

    return {
        'factor': factor,
        'hold_days': hold_days,
        'samples': len(ic_series),
        'ic_mean': round(ic_mean * 100, 4),  # 转百分比
        'ic_std': round(ic_std * 100, 4),
        'ic_ir': round(ic_ir, 4),
        'ic_pos_pct': round(ic_pos_pct * 100, 2),
        'date_range': f'{ic_series[0][0]} ~ {ic_series[-1][0]}',
    }


def main(hold_days=20, lookback_days=180):
    conn = pymysql.connect(**DB)
    print('=' * 80)
    print(f'因子IC监控 (持仓{hold_days}日, 回看{lookback_days}天)')
    print('=' * 80)

    factors = [
        'box_breakout', 'second_breakout', 'macd_golden', 'expma_golden',
        'gap_up', 'one_yang_3ma', 'ma_bull', 'ma5_cross_10',
        'shrink_pullback', 'new_high_20', 'limit_up',
        'volume_ratio_high', 'kline_reversal', 'above_ma20'
    ]

    results = []
    for f in factors:
        r = calc_factor_ic(conn, f, hold_days, lookback_days)
        if r:
            results.append(r)

    results.sort(key=lambda x: x['ic_ir'], reverse=True)

    print()
    print(f'{"因子":<20} {"样本":<6} {"IC均值%":<10} {"IC标准差":<10} {"IR":<8} {"胜率%":<8} {"日期范围"}')
    print('-' * 100)
    for r in results:
        # 标记有效（IR>0.5，胜率>55%）
        marker = '✅' if r['ic_ir'] > 0.5 and r['ic_pos_pct'] > 55 else ('⚠️ ' if r['ic_ir'] < 0 or r['ic_pos_pct'] < 45 else '  ')
        print(f'{marker} {r["factor"]:<18} {r["samples"]:<6} {r["ic_mean"]:<10.3f} '
              f'{r["ic_std"]:<10.3f} {r["ic_ir"]:<8.3f} {r["ic_pos_pct"]:<8.2f} {r["date_range"]}')

    print()
    print('判断标准:')
    print('  ✅ 优秀: IR>0.5 且 胜率>55%')
    print('  ⚠️  失效: IR<0 或 胜率<45%')
    print('  其他: 一般')

    conn.close()
    return results


if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('--hold-days', type=int, default=20)
    p.add_argument('--lookback-days', type=int, default=180)
    args = p.parse_args()
    main(args.hold_days, args.lookback_days)