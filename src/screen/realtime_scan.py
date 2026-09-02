#!/usr/bin/env python3
"""
14:30 实时二次突破扫描
- 拉全市场实时价（新浪接口）
- 拉过去 5 天的 K 线（最新K线 + 前4天）
- 找出二次突破股票（当前价破前4天高点，且前1~4天有过突破）
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
    返回: {dm: {name, current, open, prev_close, high, low, ...}}
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
        # var hq_str_sh600519="贵州茅台,1297.99,1293.09,1300.00,1305.00,1295.50,...,时间戳";
        try:
            left, right = line.split('=', 1)
            code = left.replace('var hq_str_', '').strip()
            payload = right.strip().rstrip(';').strip('"')
            if not payload:
                continue
            fields = payload.split(',')
            # 解析 jys + dm
            jys = 'sh' if code.startswith('sh') else ('sz' if code.startswith('sz') else 'bj')
            dm = code[2:]
            # 新浪字段顺序（参考 sync_daily_sina.py）：
            # 0=名称, 1=今开, 2=昨收, 3=当前价, 4=今高, 5=今低
            # ...
            # 30=日期, 31=时间
            name = fields[0]
            current = float(fields[3]) if fields[3] else None
            prev_close = float(fields[2]) if fields[2] else None
            high = float(fields[4]) if fields[4] else None
            low = float(fields[5]) if fields[5] else None
            open_ = float(fields[1]) if fields[1] else None
            date_str = fields[30] if len(fields) > 30 else None
            time_str = fields[31] if len(fields) > 31 else None
            if not current or not prev_close or not date_str:
                continue
            result[dm] = {
                'dm': dm, 'mc': name, 'jys': jys,
                'current': current, 'prev_close': prev_close,
                'high': high, 'low': low, 'open': open_,
                'date': date_str, 'time': time_str,
            }
        except (IndexError, ValueError) as e:
            continue
    return result


def load_klines_5d(conn):
    """加载每只股票最近 10 天 K 线（够覆盖国庆/中秋长假）
    返回: {dm: [bars]} bars按日期升序
    """
    cur = conn.cursor(pymysql.cursors.DictCursor)
    cur.execute("SELECT MAX(t) AS d FROM daily_kline")
    max_date = cur.fetchone()['d']
    start = max_date - timedelta(days=10)

    cur.execute("""
        SELECT dm, t, o, h, l, c, v
        FROM daily_kline
        WHERE t >= %s
        ORDER BY dm, t
    """, (start,))

    klines = {}
    for r in cur.fetchall():
        klines.setdefault(r['dm'], []).append(r)
    return klines


def find_breakouts(realtime, klines):
    """找出二次突破股票

    二次突破定义：
    - 当前价（实时）> 过去 4 天内（含今日）的最高收盘价 × 0.995
    - 过去 4 天内有过"前次突破"：某日收盘 > 之前 3 天最高收盘价
    - 当前价 > 前次突破日收盘价（即使是微破也算）
    """
    candidates = []

    for dm, rt in realtime.items():
        bars = klines.get(dm, [])
        if len(bars) < 4:
            continue

        current = rt['current']

        # 找出"过去 4 天内"的最高点
        # bars[-1] 是今日已存入的K线
        # 但 rt['current'] 是实时价（14:30 的盘中价），可能比今日K线更高
        # 用 prev_3_bars = 今日之前的 4 天数据
        if len(bars) < 5:
            continue
        prev_3_bars = bars[-5:-1]  # 今日之前的 4 天

        if len(prev_3_bars) < 3:
            # bars 不足 5 天（新股或近期上市），尝试用所有历史
            prev_3_bars = bars[:-1]
            if len(prev_3_bars) < 3:
                continue

        prev_high = float(max(b['h'] for b in prev_3_bars if b['h']))

        # 突破高点（缓冲 0.5%）
        if current < prev_high * 0.995:
            continue

        # 找出过去 4 天内的"前次突破"：某日 c > 它之前的最高
        prev_breakout_idx = None
        for i in range(len(prev_3_bars)):
            if i == 0:
                continue
            cur_bar = prev_3_bars[i]
            past_bars = prev_3_bars[max(-1, i-3):i]  # 之前 1-3 天
            if not past_bars:
                continue
            past_high = float(max(b['h'] for b in past_bars if b['h']))
            if cur_bar['c'] > past_high:
                prev_breakout_idx = i
                # 取最早的突破日
                break

        if prev_breakout_idx is None:
            continue

        pb = prev_3_bars[prev_breakout_idx]

        # 当前价 >= 前次突破日收盘（确实在二次突破）
        if current < pb['c']:
            continue

        # 算止损：突破前 3 天最低点 vs 当前价 -4%
        stop_loss = max(prev_high * 0.96, current * 0.96)

        candidates.append({
            'dm': dm,
            'mc': rt['mc'],
            'current_price': current,
            'prev_close': rt['prev_close'],
            'pct_change': (current - rt['prev_close']) / rt['prev_close'] * 100,
            'prev_breakout_date': pb['t'],
            'prev_breakout_close': float(pb['c']),
            'prev_breakout_high': float(pb['h']),
            'prev_high_4d': float(prev_high),
            'stop_loss': round(stop_loss, 2),
            'detail': {
                'now': current, 'prev_high_4d': prev_high,
                'prev_breakout_date': str(pb['t']),
                'prev_breakout_close': float(pb['c']),
                'prev_breakout_high': float(pb['h']),
                'today_open': rt['open'],
                'today_high': rt['high'],
                'today_low': rt['low'],
            }
        })

    candidates.sort(key=lambda x: x['pct_change'], reverse=True)
    return candidates


def save_results(conn, candidates, scan_time):
    """保存到 scan_realtime 表（按扫描时间批量）"""
    if not candidates:
        print('  无候选，跳过保存')
        return 0

    cur = conn.cursor()
    # 先清掉同一时间的（重新跑同一时间戳）
    cur.execute("DELETE FROM scan_realtime WHERE scan_time = %s", (scan_time,))

    rows = []
    for c in candidates:
        rows.append((
            c['dm'], c['mc'], scan_time,
            c['current_price'], c['prev_close'], round(c['pct_change'], 2),
            c['prev_breakout_date'], c['prev_breakout_close'], c['prev_breakout_high'],
            c['prev_high_4d'], c['stop_loss'],
            json.dumps(c['detail'], ensure_ascii=False, default=str)
        ))
    cur.executemany("""
        INSERT INTO scan_realtime
        (dm, mc, scan_time,
         current_price, prev_close, pct_change,
         prev_breakout_date, prev_breakout_close, prev_breakout_high,
         prev_high_4d, stop_loss, detail)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
    """, rows)
    conn.commit()
    return len(rows)


def main():
    print('=' * 80)
    print('14:30 实时二次突破扫描')
    print('=' * 80)

    conn = pymysql.connect(**DB)

    # 1. 加载所有股票 dm + jys
    cur = conn.cursor()
    cur.execute("SELECT dm, jys FROM stock_basic WHERE jys IS NOT NULL")
    all_stocks = [(r[0], r[1].lower()) for r in cur.fetchall() if r[1]]
    print(f'共 {len(all_stocks)} 只股票')

    # 2. 加载 5 天 K 线
    print('加载 K 线...')
    klines = load_klines_5d(conn)
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
        if (i // batch_size) % 10 == 0:
            elapsed = time.time() - t0
            print(f'  {i+len(batch)}/{len(all_stocks)} 拉取到{len(realtime)} 耗时{elapsed:.1f}秒')
    print(f'共拉取到 {len(realtime)} 只实时价，耗时 {time.time()-t0:.1f}秒')

    # 4. 扫描二次突破
    print('\n扫描二次突破...')
    candidates = find_breakouts(realtime, klines)
    print(f'找到 {len(candidates)} 只候选')

    # 5. 保存
    scan_time = datetime.now()
    saved = save_results(conn, candidates, scan_time)
    print(f'\n保存 {saved} 条到 scan_realtime 表')
    print(f'扫描时间: {scan_time}')

    # 6. 显示 Top 10
    print('\nTop 10 候选:')
    print(f'{"代码":<8} {"名称":<10} {"当前价":<8} {"涨跌幅":<8} {"前4天高":<8} {"前次突破日":<12} {"前次突破价":<10} {"止损"}')
    print('-' * 80)
    for c in candidates[:10]:
        print(f'{c["dm"]:<8} {c["mc"][:8]:<10} {c["current_price"]:<8.2f} '
              f'{c["pct_change"]:+6.2f}%  {c["prev_high_4d"]:<8.2f} '
              f'{str(c["prev_breakout_date"]):<12} {c["prev_breakout_close"]:<10.2f} {c["stop_loss"]}')

    conn.close()


if __name__ == '__main__':
    main()