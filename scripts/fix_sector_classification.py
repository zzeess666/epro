#!/usr/bin/env python3
"""
板块分类修正脚本
- 重新识别 sector_type
- 补齐 sector_basic 缺失的板块
"""
import os
import sys
import pymysql
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config.config import MAIRUI_API_KEYS

TOKEN = MAIRUI_API_KEYS[0]
BASE = 'https://api.mairuiapi.com'

DB_CONFIG = {
    'host': '127.0.0.1',
    'port': 3306,
    'user': 'epro',
    'password': 'nTWTkkhfYxnbEhFp',
    'database': 'epro',
    'charset': 'utf8mb4',
}


def classify_sector(code, name):
    """根据代码和名称识别 sector_type"""
    if not code:
        return 'unknown'
    if code.startswith('sw2_'):
        return 'sw2'
    if code.startswith('sw_'):
        return 'sw_yx'  # 申万一级
    if code.startswith('chgn_'):
        return 'hot_concept'  # 热门概念
    if code.startswith('gn_'):
        return 'concept'  # 概念板块
    if code.startswith('diyu_'):
        return 'region'  # 地域板块
    if code.startswith('hangye_'):
        return 'csrc'  # 证监会行业
    if code.startswith('zhishu_'):
        return 'index_member'  # 指数成分
    if code in ('hs300', 'zz500', 'sz50'):
        return 'index_member'
    if code in ('sh_a', 'sz_a', 'hs_a'):
        return 'market_type'
    return 'other'


def fix_classification(conn):
    """修正 stock_sector 中的 sector_type"""
    print('=== 修正分类 ===')
    cur = conn.cursor()
    cur.execute("SELECT dm, sector_code FROM stock_sector")
    rows = cur.fetchall()
    print(f'  共 {len(rows)} 条记录')

    # 加载 sector_basic 的 name 信息
    cur.execute("SELECT code, name FROM sector_basic")
    code_name = {r[0]: r[1] for r in cur.fetchall()}

    updated = 0
    type_counter = {}
    updates = []
    for dm, sector_code in rows:
        name = code_name.get(sector_code, '')
        new_type = classify_sector(sector_code, name)
        type_counter[new_type] = type_counter.get(new_type, 0) + 1
        updates.append((new_type, dm, sector_code))
        updated += 1

    # 批量更新
    cur.executemany("UPDATE stock_sector SET sector_type=%s WHERE dm=%s AND sector_code=%s", updates)
    conn.commit()
    print(f'  更新 {updated} 条')
    print(f'  类型分布:')
    for t, cnt in sorted(type_counter.items(), key=lambda x: -x[1]):
        print(f'    {t:<20} {cnt}')


def add_missing_sectors(conn):
    """补充 sector_basic 缺失的板块（来自 stock_sector）"""
    print('\n=== 补齐 sector_basic ===')
    cur = conn.cursor()
    cur.execute("""
        SELECT DISTINCT ss.sector_code,
               COALESCE(sb.name, CONCAT('代码:', ss.sector_code)) as name,
               ss.sector_type
        FROM stock_sector ss
        LEFT JOIN sector_basic sb ON ss.sector_code = sb.code
        WHERE sb.code IS NULL
    """)
    rows = cur.fetchall()
    print(f'  缺失 {len(rows)} 个板块')

    if rows:
        # 推断 name 和 level
        updates = []
        for code, name, stype in rows:
            # name 从 sector_basic 取不到，用类型前缀
            if stype == 'sw_yx':
                clean_name = code.replace('sw_', '申万-')
            elif stype == 'sw2':
                clean_name = code.replace('sw2_', '申万二级-')
            else:
                clean_name = code
            updates.append((code, clean_name, 'mairui', stype, 0))
        cur.executemany("""
            INSERT INTO sector_basic (code, name, source, level, stocks_count)
            VALUES (%s,%s,%s,%s,%s)
            ON DUPLICATE KEY UPDATE level=VALUES(level)
        """, updates)
        conn.commit()
        print(f'  已补齐 {len(updates)} 个板块')


def update_sector_count(conn):
    """更新板块成分股数"""
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


def analyze(conn):
    """最终分析"""
    print('\n=== 板块分析 ===')
    cur = conn.cursor()

    # 板块类型分布
    print('\n板块类型分布:')
    cur.execute("""
        SELECT sector_type, COUNT(*) AS sectors
        FROM sector_basic
        WHERE stocks_count > 0
        GROUP BY sector_type
    """)
    for r in cur.fetchall():
        print(f'  {r[0]:<20} {r[1]} 个板块')

    # 申万一级 Top 15
    print('\n申万一级行业 Top 15:')
    cur.execute("""
        SELECT code, name, stocks_count
        FROM sector_basic
        WHERE level = 'sw_yx' AND stocks_count > 0
        ORDER BY stocks_count DESC
        LIMIT 15
    """)
    for r in cur.fetchall():
        print(f'  {r[0]:<15} {r[1]:<20} {r[2]}只')

    # 申万二级 Top 15
    print('\n申万二级行业 Top 15:')
    cur.execute("""
        SELECT code, name, stocks_count
        FROM sector_basic
        WHERE level = 'sw2' AND stocks_count > 0
        ORDER BY stocks_count DESC
        LIMIT 15
    """)
    for r in cur.fetchall():
        print(f'  {r[0]:<20} {r[1]:<30} {r[2]}只')

    # 热门概念 Top 20
    print('\n热门概念 Top 20:')
    cur.execute("""
        SELECT code, name, stocks_count
        FROM sector_basic
        WHERE level = 'hot_concept' AND stocks_count > 0
        ORDER BY stocks_count DESC
        LIMIT 20
    """)
    for r in cur.fetchall():
        print(f'  {r[0]:<20} {r[1]:<30} {r[2]}只')

    # 概念板块 Top 20
    print('\n概念板块 Top 20:')
    cur.execute("""
        SELECT code, name, stocks_count
        FROM sector_basic
        WHERE level = 'concept' AND stocks_count > 0
        ORDER BY stocks_count DESC
        LIMIT 20
    """)
    for r in cur.fetchall():
        print(f'  {r[0]:<20} {r[1]:<30} {r[2]}只')

    # 地域板块 Top 10
    print('\n地域板块 Top 10:')
    cur.execute("""
        SELECT code, name, stocks_count
        FROM sector_basic
        WHERE level = 'region' AND stocks_count > 0
        ORDER BY stocks_count DESC
        LIMIT 10
    """)
    for r in cur.fetchall():
        print(f'  {r[0]:<20} {r[1]:<30} {r[2]}只')


if __name__ == '__main__':
    conn = pymysql.connect(**DB_CONFIG)
    fix_classification(conn)
    add_missing_sectors(conn)
    update_sector_count(conn)
    analyze(conn)
    conn.close()