#!/usr/bin/env python3
"""
板块数据入库脚本
- 拉板块基础信息（primarylist + sectorslist）
- 拉股票-板块关系（zg）
"""
import os
import sys
import time
import pymysql
import requests
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config.config import MAIRUI_API_KEYS
from src.api.api_key_rotator import ApiKeyRotator, ApiKeyExhaustedError

BASE = 'https://api.mairuiapi.com'
_rotator = ApiKeyRotator()


def _get_token() -> str:
    """获取当前可用的麦蕊 API token（轮询 + 限流，超额时回退到第一个 key）"""
    try:
        return _rotator.next()
    except ApiKeyExhaustedError:
        return _rotator.keys[0]

DB_CONFIG = {
    'host': '127.0.0.1',
    'port': 3306,
    'user': 'epro',
    'password': 'nTWTkkhfYxnbEhFp',
    'database': 'epro',
    'charset': 'utf8mb4',
}


def fetch(url, timeout=10):
    try:
        r = requests.get(url, timeout=timeout)
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        print(f'  ! {url[:80]}: {e}')
    return None


def ensure_sector_tables(conn):
    """创建板块表"""
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS sector_basic (
            code VARCHAR(50) PRIMARY KEY,
            name VARCHAR(100),
            source VARCHAR(20) COMMENT 'shenwan/gn/bkzs',
            level VARCHAR(20) COMMENT 'sw_yx/sw2/sw3/BK',
            stocks_count INT DEFAULT 0,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS stock_sector (
            dm VARCHAR(10),
            sector_code VARCHAR(50),
            sector_type VARCHAR(20) COMMENT 'sw_yx/sw2/sw3/concept',
            PRIMARY KEY (dm, sector_code),
            KEY idx_sector (sector_code),
            KEY idx_dm (dm)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    conn.commit()
    print('✅ 板块表已确保存在')


def sync_sector_basic(conn):
    """拉板块基础信息"""
    print('\n=== 拉板块基础信息 ===')
    total = 0

    # 申万一级/二级/三级
    data = fetch(f'{BASE}/hslt/primarylist/{_get_token()}')
    if data and isinstance(data, list):
        cur = conn.cursor()
        rows = []
        for item in data:
            mc = item.get('mc', '')
            # 解析 sw_yx/sw2/sw3
            level = 'sw_yx'
            if mc.startswith('1000SW2'):
                level = 'sw2'
            elif mc.startswith('1000SW3'):
                level = 'sw3'
            elif mc.startswith('BKZS'):
                level = 'BKZS'
            rows.append((mc, mc, 'shenwan', level, 0))
        cur.executemany("""
            INSERT INTO sector_basic (code, name, source, level, stocks_count)
            VALUES (%s,%s,%s,%s,%s)
            ON DUPLICATE KEY UPDATE name=VALUES(name), level=VALUES(level)
        """, rows)
        conn.commit()
        total += len(rows)
        print(f'  申万板块: {len(rows)} 条')

    # 概念板块
    data = fetch(f'{BASE}/hslt/sectorslist/{_get_token()}')
    if data and isinstance(data, list):
        cur = conn.cursor()
        rows = []
        for item in data:
            code = item.get('dm', '')
            name = item.get('mc', '')
            rows.append((code, name, 'gn', 'concept', 0))
        cur.executemany("""
            INSERT INTO sector_basic (code, name, source, level, stocks_count)
            VALUES (%s,%s,%s,%s,%s)
            ON DUPLICATE KEY UPDATE name=VALUES(name), level=VALUES(level)
        """, rows)
        conn.commit()
        total += len(rows)
        print(f'  概念板块: {len(rows)} 条')

    print(f'  总计: {total} 个板块')


def sync_stock_sector(conn):
    """拉股票-板块关系"""
    print('\n=== 拉股票-板块关系（5209只）===')

    # 获取所有股票代码
    cur = conn.cursor()
    cur.execute("SELECT dm FROM stock_basic")
    stocks = [r[0] for r in cur.fetchall()]
    print(f'  共 {len(stocks)} 只股票')

    total_rows = 0
    failed = 0

    t0 = time.time()
    for i, dm in enumerate(stocks, 1):
        data = fetch(f'{BASE}/hszg/zg/{dm}/{_get_token()}')
        if data and isinstance(data, list):
            rows = []
            for item in data:
                code = item.get('code', '')
                name = item.get('name', '')
                if not code:
                    continue
                # 推断 sector_type
                stype = 'concept'
                if code.startswith('sw_yx'):
                    stype = 'sw_yx'
                elif code.startswith('sw2_'):
                    stype = 'sw2'
                elif code.startswith('sw3_'):
                    stype = 'sw3'
                elif name.startswith('沪深股市-申万二级'):
                    stype = 'sw2'
                elif name.startswith('沪深股市-申万一级'):
                    stype = 'sw_yx'
                rows.append((dm, code, stype))
            if rows:
                cur.executemany("""
                    INSERT IGNORE INTO stock_sector
                    (dm, sector_code, sector_type)
                    VALUES (%s,%s,%s)
                """, rows)
                conn.commit()
                total_rows += len(rows)
        else:
            failed += 1

        if i % 500 == 0:
            elapsed = time.time() - t0
            rate = i / elapsed
            remaining = (len(stocks) - i) / rate
            print(f'  {i}/{len(stocks)} 失败{failed} 关联{total_rows}条 速度{rate:.1f}/秒 剩余{remaining:.0f}秒')

    print(f'\n  完成: 关联{total_rows}条 失败{failed}只 耗时{time.time()-t0:.0f}秒')


def sync_sector_count(conn):
    """统计每个板块的成分股数量"""
    print('\n=== 统计板块成分股数 ===')
    cur = conn.cursor()
    cur.execute("""
        UPDATE sector_basic sb
        SET stocks_count = (
            SELECT COUNT(DISTINCT ss.dm)
            FROM stock_sector ss
            WHERE ss.sector_code = sb.code
        )
    """)
    conn.commit()
    cur.execute("SELECT COUNT(*) FROM sector_basic WHERE stocks_count > 0")
    cnt = cur.fetchone()[0]
    print(f'  已有成分股的板块: {cnt}')


def analyze_distribution(conn):
    """板块分布分析"""
    print('\n=== 板块分布分析 ===')
    cur = conn.cursor()

    # 按类型统计
    cur.execute("""
        SELECT sector_type, COUNT(DISTINCT sector_code) AS sectors,
               COUNT(DISTINCT dm) AS stocks
        FROM stock_sector
        GROUP BY sector_type
    """)
    print('\n板块类型分布:')
    print(f'{"类型":<10} {"板块数":<8} {"股票数":<8}')
    for r in cur.fetchall():
        print(f'{r[0]:<10} {r[1]:<8} {r[2]:<8}')

    # 申万一级行业Top 10（按股票数）
    print('\n申万一级行业 Top 10（按股票数）:')
    cur.execute("""
        SELECT sb.code, sb.name, COUNT(DISTINCT ss.dm) AS stocks
        FROM sector_basic sb
        JOIN stock_sector ss ON ss.sector_code = sb.code
        WHERE sb.level = 'sw_yx'
        GROUP BY sb.code, sb.name
        ORDER BY stocks DESC
        LIMIT 10
    """)
    for r in cur.fetchall():
        print(f'  {r[0]:<15} {r[1]:<20} {r[2]}只')

    # 申万二级行业Top 10
    print('\n申万二级行业 Top 10:')
    cur.execute("""
        SELECT sb.code, sb.name, COUNT(DISTINCT ss.dm) AS stocks
        FROM sector_basic sb
        JOIN stock_sector ss ON ss.sector_code = sb.code
        WHERE sb.level = 'sw2'
        GROUP BY sb.code, sb.name
        ORDER BY stocks DESC
        LIMIT 10
    """)
    for r in cur.fetchall():
        print(f'  {r[0]:<20} {r[1]:<30} {r[2]}只')

    # 热门概念板块 Top 15
    print('\n热门概念板块 Top 15:')
    cur.execute("""
        SELECT sb.code, sb.name, COUNT(DISTINCT ss.dm) AS stocks
        FROM sector_basic sb
        JOIN stock_sector ss ON ss.sector_code = sb.code
        WHERE sb.level = 'concept'
        GROUP BY sb.code, sb.name
        ORDER BY stocks DESC
        LIMIT 15
    """)
    for r in cur.fetchall():
        print(f'  {r[0]:<15} {r[1]:<30} {r[2]}只')


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--analyze', action='store_true', help='只做分析不拉取')
    parser.add_argument('--skip-zg', action='store_true', help='跳过股票-板块关系（量大）')
    args = parser.parse_args()

    conn = pymysql.connect(**DB_CONFIG)

    if not args.analyze:
        ensure_sector_tables(conn)
        sync_sector_basic(conn)
        if not args.skip_zg:
            sync_stock_sector(conn)
        sync_sector_count(conn)

    analyze_distribution(conn)
    conn.close()