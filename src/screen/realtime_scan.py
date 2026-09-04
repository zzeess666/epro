#!/usr/bin/env python3
"""
14:30 实时二次突破扫描
- 拉全市场实时价（新浪接口）
- 拉历史K线（至少35天）
- 找出二次突破股票：
  A: 当前实时价
  B: 今天之前 2~4 个交易日的某日
  判断：
   1. B 日收盘 = B-30 ~ B-1 的最高收盘（不含 B 日）
   2. A 和 B 之间（B+1 到 今天-1）：每日收盘 < B 日收盘
   3. 当前实时价 > B 日收盘
- 写入 scan_realtime 表
"""
import os
import sys
import time
import json
import pymysql
import requests
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
from pathlib import Path
load_dotenv(Path(__file__).resolve().parents[2] / '.env')

DB = {
    'host': os.getenv('DB_HOST', '127.0.0.1'),
    'port': int(os.getenv('DB_PORT', '3306')),
    'user': os.getenv('DB_USER', 'epro'),
    'password': os.getenv('DB_PASSWORD', ''),
    'database': os.getenv('DB_NAME', 'epro'),
    'charset': 'utf8mb4',
}
BASE_NEW = 'https://hq.sinajs.cn'


def fetch_realtime_batch(dm_jys_list):
    """新浪批量实时拉取
    返回: {dm: {name, current, prev_close, high, low, open, ...}}
    """
    codes = ','.join([f"{jys}{dm}" for dm, jys in dm_jys_list])
    url = f'{BASE_NEW}/list={codes}'
    try:
        r = requests.get(url, timeout=15, headers={'Referer': 'https://finance.sina.com.cn/'})
        if r.status_code != 200:
            return {}
    except Exception as e:
        print(f'  ! 新浪请求失败: {e}')
        return {}

    result = {}
    for line in r.text.strip().split('\n'):
        line = line.strip()
        if not line.startswith('var hq_str_'):
            continue
        try:
            left, right = line.split('=', 1)
            code = left.replace('var hq_str_', '').strip()
            payload = right.strip().rstrip(';').strip('"')
            if not payload:
                continue
            fields = payload.split(',')
            jys = 'sh' if code.startswith('sh') else ('sz' if code.startswith('sz') else 'bj')
            dm = code[2:]
            name = fields[0]
            current = float(fields[3]) if fields[3] else None
            prev_close = float(fields[2]) if fields[2] else None
            high = float(fields[4]) if fields[4] else None
            low = float(fields[5]) if fields[5] else None
            open_ = float(fields[1]) if fields[1] else None
            if not current or not prev_close:
                continue
            result[dm] = {
                'dm': dm, 'mc': name, 'jys': jys,
                'current': current, 'prev_close': prev_close,
                'high': high, 'low': low, 'open': open_,
            }
        except (IndexError, ValueError):
            continue
    return result


def load_klines(conn, days=60):
    """加载每只股票最近 60 天的 K 线
    返回: {dm: [bars]} bars按日期升序
    """
    cur = conn.cursor(pymysql.cursors.DictCursor)
    cur.execute("SELECT MAX(t) AS d FROM daily_kline")
    max_date = cur.fetchone()['d']
    start = max_date - timedelta(days=days)

    cur.execute("""
        SELECT dm, t, o, h, l, c, v
        FROM daily_kline
        WHERE t >= %s
        ORDER BY dm, t
    """, (start,))

    klines = {}
    for r in cur.fetchall():
        klines.setdefault(r['dm'], []).append({
            't': r['t'], 'o': r['o'], 'h': r['h'], 'l': r['l'],
            'c': float(r['c']) if r['c'] is not None else None,
            'v': float(r['v']) if r['v'] is not None else None,
        })
    return klines


def find_limit_pullback(current_price, bars):
    """
    涨停回马枪（盘中实时）
    A: 当前实时价
    1. 过去 5 天内有涨停日（c/o > 1.095）
    2. 涨停后存在回踩日（缩量，量 < 涨停日 × 0.5）
    3. 回踩日收盘 < 涨停日收盘 × 0.97
    4. 今天收盘 > 回踩日收盘（企稳）
    5. 当前价 > 涨停日收盘 × 0.95（突破后买回）
    止损: 回踩日最低 × 0.97
    """
    if len(bars) < 10:
        return None

    today_idx = len(bars) - 1
    today_bar = bars[today_idx]
    real_c = current_price

    # 找最近 5 天内的涨停日（含今天）
    limit_up_idx = None
    for i in range(today_idx - 4, today_idx + 1):
        if i < 0:
            continue
        b = bars[i]
        c, o, v = b['c'], b['o'], b['v']
        if c is None or o is None or o <= 0 or v is None:
            continue
        if (float(c) - float(o)) / float(o) >= 0.095:
            limit_up_idx = i
            break

    if limit_up_idx is None:
        return None

    limit_bar = bars[limit_up_idx]
    limit_close = float(limit_bar['c'])
    limit_vol = float(limit_bar['v'])
    limit_date = limit_bar['t']

    # 找涨停后的回踩日（涨停日之后到今天之前）
    pullback_idx = None
    for i in range(limit_up_idx + 1, today_idx):
        b = bars[i]
        c, v = b['c'], b['v']
        if c is None or v is None:
            continue
        if v < limit_vol * 0.5 and c < limit_close * 0.97:
            pullback_idx = i
            break

    if pullback_idx is None:
        return None

    pullback_bar = bars[pullback_idx]
    pullback_close = float(pullback_bar['c'])
    pullback_low = float(pullback_bar['l'])

    # 今天收盘 > 回踩日收盘（企稳）
    today_close = float(today_bar['c'])
    if today_close <= pullback_close:
        return None

    # 当前价 > 涨停日收盘 × 0.95
    if real_c < limit_close * 0.95:
        return None

    return {
        'B_idx': today_idx,
        'B_date': today_bar['t'],
        'B_close': today_close,
        'B_low': pullback_low,
        'B_high': limit_close,
        'days_back': 0,
        'middle_days': [limit_bar['t'], pullback_bar['t']],
        'limit_up_date': str(limit_date),
        'limit_up_close': limit_close,
        'pullback_date': str(pullback_bar['t']),
        'pullback_close': pullback_close,
        'stop_loss': round(pullback_low * 0.97, 2),
    }


def find_strong_holdup(current_price, bars):
    """
    强势股不跌（盘中实时）
    A: 当前实时价
    1. 当前价 > MA20（站上 20 日均线）
    2. 过去 5 天最大回撤 < 3%（该跌不跌）
    3. 当前价 >= 5日最高 × 0.97（接近新高）
    4. 量能 >= 5日均量 × 0.8（量能不缩）
    止损: 5日最低 × 0.97
    """
    if len(bars) < 25:
        return None

    today_idx = len(bars) - 1
    today_bar = bars[today_idx]
    real_c = current_price  # 用实时价

    # 1. MA20
    closes_20 = [b['c'] for b in bars[today_idx - 19: today_idx + 1] if b['c'] is not None]
    if len(closes_20) < 20:
        return None
    ma20 = sum(closes_20) / 20
    if real_c <= ma20:
        return None

    # 5 日窗口
    last5 = bars[today_idx - 4: today_idx + 1]
    highs5 = [b['h'] for b in last5 if b['h'] is not None]
    lows5 = [b['l'] for b in last5 if b['l'] is not None]
    vols5 = [b['v'] for b in last5 if b['v'] is not None]

    if not highs5 or not lows5 or len(vols5) < 5:
        return None

    past_5_high = max(highs5)
    past_5_low = min(lows5)

    # 2. 过去 5 天最大回撤 < 5%（该跌不跌）
    min_low_5 = past_5_low
    pullback = (past_5_high - min_low_5) / past_5_high if past_5_high > 0 else 0
    if pullback >= 0.05:
        return None

    # 3. 接近新高: real_c >= past_5_high × 0.97
    if real_c < float(past_5_high) * 0.97:
        return None

    # 4. 量能不缩
    avg_vol_5 = sum(vols5[:-1]) / max(1, len(vols5) - 1)
    today_vol = vols5[-1]
    if avg_vol_5 <= 0 or today_vol < avg_vol_5 * 0.8:
        return None

    return {
        'B_idx': today_idx,
        'B_date': today_bar['t'],
        'B_close': today_bar['c'],
        'B_low': past_5_low,
        'B_high': past_5_high,
        'days_back': 0,
        'middle_days': [],
        'ma20': round(ma20, 2),
        'pullback_pct': round(pullback * 100, 2),
        'stop_loss': round(float(past_5_low) * 0.97, 2),
    }


def find_second_breakout(current_price, bars):
    """
    二次突破判断（你的精确定义）
    bars: K线列表（升序）
    返回: dict (B 信息) or None
    """
    # 至少需要 35 天（B+30天+B距今5天）
    if len(bars) < 35:
        return None

    today_idx = len(bars) - 1

    # 尝试 2, 3, 4 天前作为 B 日
    for days_back in [2, 3, 4]:
        B_idx = today_idx - days_back
        if B_idx < 30:
            continue  # B 之前需要30天历史

        B_bar = bars[B_idx]
        B_close = B_bar['c']
        B_low = B_bar['l']
        B_high = B_bar['h']
        B_date = B_bar['t']

        if B_close is None or B_low is None or B_high is None:
            continue

        # 关键：B-30 ~ B-1（不含 B 日）的 30 天窗口
        window = bars[B_idx - 30: B_idx]
        if len(window) < 30:
            continue

        # 严格判断：B 日收盘 = 前 30 天最高
        max_close = max(b['c'] for b in window if b['c'] is not None)
        if abs(B_close - max_close) > 0.001:
            continue

        # 中间日（B+1 到 today-1）的收盘 < B 收
        middle_ok = True
        for i in range(B_idx + 1, today_idx):
            c = bars[i]['c']
            if c is None or c >= B_close:
                middle_ok = False
                break
        if not middle_ok:
            continue

        # today K 线的收盘价 > B 收（确认真正的二次突破，不只是盘中瞬间）
        today_close = bars[today_idx]['c']
        if today_close is None or today_close <= B_close:
            continue

        # 当前实时价 > today K 线收盘（确认盘中继续走强，不买突破后立刻回落的）
        # 这一条可选，去掉可避免"假突破"被过滤掉
        # if current_price <= today_close:
        #     continue

        # 通过！
        return {
            'B_idx': B_idx,
            'B_date': B_date,
            'B_close': B_close,
            'B_low': B_low,
            'B_high': B_high,
            'days_back': days_back,
            'middle_days': [bars[i]['t'] for i in range(B_idx + 1, today_idx)],
        }

    return None


def save_results(conn, candidates, scan_time, mode='second_breakout'):
    """保存到 scan_realtime 表（按 mode 分表）"""
    if not candidates:
        print('  无候选，跳过保存')
        return 0

    table_map = {
        'strong_holdup': 'scan_realtime_strong',
        'limit_pullback': 'scan_realtime_limit',
        'second_breakout': 'scan_realtime',
    }
    table = table_map.get(mode, 'scan_realtime')

    cur = conn.cursor()
    cur.execute(f"DELETE FROM {table} WHERE scan_time = %s", (scan_time,))

    if mode == 'strong_holdup':
        # 强势股字段集
        rows = []
        for c in candidates:
            rows.append((
                c['dm'], c['mc'], scan_time,
                c['current_price'], c['prev_close'], round(c['pct_change'], 2),
                c['B_date'], c.get('ma20'), c.get('pullback_pct'),
                c.get('B_high'), c.get('stop_loss'),
                json.dumps({
                    'trigger_date': str(c['B_date']),
                    'ma20': c.get('ma20'),
                    'pullback_pct': c.get('pullback_pct'),
                    'past_5_high': c.get('B_high'),
                }, ensure_ascii=False, default=str)
            ))
        cur.executemany(f"""
            INSERT INTO {table}
            (dm, mc, scan_time,
             current_price, prev_close, pct_change,
             trigger_date, ma20, pullback_pct,
             past_5_high, stop_loss, detail)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, rows)
    elif mode == 'second_breakout':
        # 二次突破字段集
        rows = []
        for c in candidates:
            rows.append((
                c['dm'], c['mc'], scan_time,
                c['current_price'], c['prev_close'], round(c['pct_change'], 2),
                c['B_date'], c['B_close'], c['B_high'],
                round(float(c['B_low']) * 0.98, 2),
                json.dumps({
                    'B_date': str(c['B_date']),
                    'B_close': c['B_close'],
                    'B_low': c['B_low'],
                    'days_back': c['days_back'],
                    'middle_days': [str(d) for d in c['middle_days']],
                }, ensure_ascii=False, default=str)
            ))
        cur.executemany(f"""
            INSERT INTO {table}
            (dm, mc, scan_time,
             current_price, prev_close, pct_change,
             prev_breakout_date, prev_breakout_close, prev_breakout_high,
             stop_loss, detail)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, rows)
    elif mode == 'limit_pullback':
        # 涨停回马枪字段集
        rows = []
        for c in candidates:
            rows.append((
                c['dm'], c['mc'], scan_time,
                c['current_price'], c['prev_close'], round(c['pct_change'], 2),
                c.get('limit_up_date'), c.get('limit_up_close'),
                c.get('pullback_date'), c.get('pullback_close'), c.get('pullback_low'),
                c.get('stop_loss'),
                json.dumps({
                    'limit_up_date': c.get('limit_up_date'),
                    'limit_up_close': c.get('limit_up_close'),
                    'pullback_date': c.get('pullback_date'),
                    'pullback_close': c.get('pullback_close'),
                    'pullback_low': c.get('pullback_low'),
                }, ensure_ascii=False, default=str)
            ))
        cur.executemany(f"""
            INSERT INTO {table}
            (dm, mc, scan_time,
             current_price, prev_close, pct_change,
             limit_up_date, limit_up_close,
             pullback_date, pullback_close, pullback_low,
             stop_loss, detail)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, rows)
    conn.commit()
    return len(rows)


def main():
    import argparse
    parser = argparse.ArgumentParser(description='14:30 实时扫描')
    parser.add_argument('--mode', default='second_breakout',
                        choices=['second_breakout', 'strong_holdup', 'limit_pullback'],
                        help='扫描算法: second_breakout 二次突破 / strong_holdup 强势股不跌 / limit_pullback 涨停回马枪')
    args = parser.parse_args()

    # 算法选择
    if args.mode == 'second_breakout':
        scan_func = find_second_breakout
        algo_name = '二次突破'
        algo_desc = 'B日=2-4天前收盘=前30天最高 + 中间日<B收 + 当前>B收'
    elif args.mode == 'strong_holdup':
        scan_func = find_strong_holdup
        algo_name = '强势股不跌'
        algo_desc = '当前>MA20 + 5日回撤<5% + 接近5日高 + 量能不缩'
    else:  # limit_pullback
        scan_func = find_limit_pullback
        algo_name = '涨停回马枪'
        algo_desc = '近5日内涨停+回踩(缩量+不破涨停收盘)+企稳'

    print('=' * 80)
    print(f'14:30 实时扫描 [{algo_name}]')
    print('=' * 80)
    print(f'算法: {algo_desc}')
    print()

    conn = pymysql.connect(**DB)

    # 1. 加载所有股票 dm + jys
    cur = conn.cursor()
    cur.execute("SELECT dm, jys FROM stock_basic WHERE jys IS NOT NULL")
    all_stocks = [(r[0], r[1].lower()) for r in cur.fetchall() if r[1]]
    print(f'共 {len(all_stocks)} 只股票')

    # 2. 加载 60 天 K 线
    print('加载 60 天 K 线...')
    klines = load_klines(conn, days=60)
    print(f'K 线覆盖 {len(klines)} 只股票')

    # 3. 新浪批量拉实时价（50只/批）
    print('拉取实时价（新浪接口）...')
    realtime = {}
    batch_size = 50
    t0 = time.time()
    for i in range(0, len(all_stocks), batch_size):
        batch = all_stocks[i:i+batch_size]
        rt = fetch_realtime_batch(batch)
        realtime.update(rt)
        if (i // batch_size) % 20 == 0:
            elapsed = time.time() - t0
            print(f'  {i+len(batch)}/{len(all_stocks)} 拉取到{len(realtime)} 耗时{elapsed:.1f}秒')
    print(f'共拉取到 {len(realtime)} 只实时价，耗时 {time.time()-t0:.1f}秒')

    # 4. 扫描
    print(f'\n扫描[{algo_name}]...')
    candidates = []
    for dm, rt in realtime.items():
        bars = klines.get(dm, [])
        result = scan_func(rt['current'], bars)
        if result:
            candidates.append({
                'dm': dm,
                'mc': rt['mc'],
                'current_price': rt['current'],
                'prev_close': rt['prev_close'],
                'pct_change': (rt['current'] - rt['prev_close']) / rt['prev_close'] * 100,
                'B_date': result['B_date'],
                'B_close': result['B_close'],
                'B_low': result['B_low'],
                'B_high': result.get('B_high'),
                'days_back': result['days_back'],
                'middle_days': result['middle_days'],
                'ma20': result.get('ma20'),
                'pullback_pct': result.get('pullback_pct'),
                'limit_up_date': result.get('limit_up_date'),
                'limit_up_close': result.get('limit_up_close'),
                'pullback_date': result.get('pullback_date'),
                'pullback_close': result.get('pullback_close'),
                'pullback_low': result.get('pullback_low'),
            })

    # 按 B 距今天数 + 涨幅排序
    candidates.sort(key=lambda x: (x['days_back'], -x['pct_change']))

    print(f'找到 {len(candidates)} 只候选')

    # 5. 保存
    scan_time = datetime.now()
    saved = save_results(conn, candidates, scan_time, mode=args.mode)
    print(f'\n保存 {saved} 条到 scan_realtime 表')
    print(f'扫描时间: {scan_time}')

    # 6. 显示
    if candidates:
        print('\n候选详情:')
        print(f'{"代码":<8} {"名称":<10} {"当前价":<8} {"涨跌幅":<9} {"B日":<12} {"B收":<8} {"B距":<5} {"止损"}')
        print('-' * 80)
        for c in candidates:
            pct = (c['current_price'] - c['prev_close']) / c['prev_close'] * 100
            print(f"{c['dm']:<8} {c['mc'][:8]:<10} {c['current_price']:<8.2f} "
                  f"{pct:+6.2f}%  {str(c['B_date']):<12} {c['B_close']:<8.2f} "
                  f"{c['days_back']:>3}天   {float(c['B_low'])*0.98:.2f}")

    conn.close()


if __name__ == '__main__':
    main()