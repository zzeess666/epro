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

        # 当前实时价 > B 收
        if current_price <= B_close:
            continue

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


def save_results(conn, candidates, scan_time):
    """保存到 scan_realtime 表"""
    if not candidates:
        print('  无候选，跳过保存')
        return 0

    cur = conn.cursor()
    cur.execute("DELETE FROM scan_realtime WHERE scan_time = %s", (scan_time,))

    rows = []
    for c in candidates:
        rows.append((
            c['dm'], c['mc'], scan_time,
            c['current_price'], c['prev_close'], round(c['pct_change'], 2),
            c['B_date'], c['B_close'], c['B_high'],
            round(float(c['B_low']) * 0.98, 2),  # 止损 = B低 × 0.98
            json.dumps({
                'B_date': str(c['B_date']),
                'B_close': c['B_close'],
                'B_low': c['B_low'],
                'days_back': c['days_back'],
                'middle_days': [str(d) for d in c['middle_days']],
            }, ensure_ascii=False, default=str)
        ))
    cur.executemany("""
        INSERT INTO scan_realtime
        (dm, mc, scan_time,
         current_price, prev_close, pct_change,
         prev_breakout_date, prev_breakout_close, prev_breakout_high,
         stop_loss, detail)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
    """, rows)
    conn.commit()
    return len(rows)


def main():
    print('=' * 80)
    print('14:30 实时二次突破扫描（按你的精确定义）')
    print('=' * 80)
    print('定义:')
    print('  B日 = 今天之前 2~4 个交易日')
    print('  B 日收盘 = B-30 ~ B-1 的最高收盘（不含 B 日）')
    print('  中间日（B+1 到 今天-1）收盘 < B 收')
    print('  当前实时价 > B 收')
    print('  止损 = B 低 × 0.98')
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

    # 4. 扫描二次突破
    print('\n扫描二次突破...')
    candidates = []
    for dm, rt in realtime.items():
        bars = klines.get(dm, [])
        result = find_second_breakout(rt['current'], bars)
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
                'B_high': result['B_high'],
                'days_back': result['days_back'],
                'middle_days': result['middle_days'],
            })

    # 按 B 距今天数 + 涨幅排序
    candidates.sort(key=lambda x: (x['days_back'], -x['pct_change']))

    print(f'找到 {len(candidates)} 只候选')

    # 5. 保存
    scan_time = datetime.now()
    saved = save_results(conn, candidates, scan_time)
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