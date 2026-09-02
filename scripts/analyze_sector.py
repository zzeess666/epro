#!/usr/bin/env python3
"""
板块强弱分析工具
- 申万一级行业涨跌、估值、利润增长
- 板块成分股Top
- 热门概念热度
"""
import pymysql
from datetime import date, datetime

DB = {
    'host': '127.0.0.1', 'port': 3306, 'user': 'epro',
    'password': 'nTWTkkhfYxnbEhFp', 'database': 'epro', 'charset': 'utf8mb4',
}


def analyze_shenwan_top():
    """申万一级行业综合评分"""
    conn = pymysql.connect(**DB)
    cur = conn.cursor(pymysql.cursors.DictCursor)

    # 最新财报日期
    cur.execute("SELECT MAX(report_date) AS max_date FROM financial_quarterly")
    max_date = cur.fetchone()['max_date']
    print(f'数据日期: {max_date}\n')

    cur.execute("""
        SELECT
            sb.code AS sector_code,
            sb.name AS sector_name,
            COUNT(DISTINCT ss.dm) AS stock_count,
            ROUND(AVG(fq.roe_ttm), 2) AS avg_roe,
            ROUND(AVG(fq.gross_margin), 2) AS avg_gross_margin,
            ROUND(AVG(fq.debt_ratio), 2) AS avg_debt_ratio,
            ROUND(AVG(fq.rev_yoy), 2) AS avg_rev_yoy,
            ROUND(AVG(fq.profit_yoy), 2) AS avg_profit_yoy,
            SUM(CASE WHEN fq.roe_ttm > 10 THEN 1 ELSE 0 END) AS high_roe_count
        FROM sector_basic sb
        JOIN stock_sector ss ON ss.sector_code = sb.code
        LEFT JOIN financial_quarterly fq ON ss.dm = fq.dm
            AND fq.report_date = %s
        WHERE sb.code LIKE 'sw_%%' AND sb.code NOT LIKE 'sw2_%%'
        GROUP BY sb.code, sb.name
        HAVING stock_count >= 10
        ORDER BY avg_roe DESC
    """, (max_date,))

    rows = cur.fetchall()
    print(f'申万一级行业 ({len(rows)} 个, 要求 >=10 只成分股):')
    print('=' * 100)
    print(f'{"代码":<10} {"名称":<12} {"股票数":<6} {"ROE%":<7} {"毛利率%":<8} {"负债率%":<7} {"营收增%":<7} {"利润增%":<8} {"高ROE数"}')
    print('-' * 100)
    for r in rows:
        print(f'{r["sector_code"]:<10} {r["sector_name"][:10]:<12} '
              f'{r["stock_count"]:<6} {r["avg_roe"] or 0:<7.2f} '
              f'{r["avg_gross_margin"] or 0:<8.2f} {r["avg_debt_ratio"] or 0:<7.2f} '
              f'{r["avg_rev_yoy"] or 0:<7.2f} {r["avg_profit_yoy"] or 0:<8.2f} '
              f'{r["high_roe_count"] or 0}')

    conn.close()
    return rows


def analyze_sector_stocks(sector_code, limit=10):
    """板块内Top股票（按ROE）"""
    conn = pymysql.connect(**DB)
    cur = conn.cursor(pymysql.cursors.DictCursor)

    cur.execute("SELECT MAX(report_date) AS max_date FROM financial_quarterly")
    max_date = cur.fetchone()['max_date']

    cur.execute("""
        SELECT
            sb.dm, st.mc,
            fq.roe_ttm, fq.gross_margin, fq.debt_ratio,
            fq.rev_yoy, fq.profit_yoy, fq.eps
        FROM stock_sector sb
        JOIN stock_basic st ON sb.dm = st.dm
        LEFT JOIN financial_quarterly fq ON sb.dm = fq.dm
            AND fq.report_date = %s
        WHERE sb.sector_code = %s
        ORDER BY fq.roe_ttm DESC
        LIMIT %s
    """, (max_date, sector_code, limit))

    print(f'\n=== {sector_code} Top {limit} (按 ROE) ===')
    print(f'{"代码":<8} {"名称":<10} {"ROE%":<8} {"毛利率%":<8} {"营收增%":<8} {"利润增%":<8} {"EPS"}')
    for r in cur.fetchall():
        mc = r['mc'][:8] if r['mc'] else ''
        print(f'{r["dm"]:<8} {mc:<10} '
              f'{r["roe_ttm"] or 0:<8.2f} {r["gross_margin"] or 0:<8.2f} '
              f'{r["rev_yoy"] or 0:<8.2f} {r["profit_yoy"] or 0:<8.2f} '
              f'{r["eps"] or 0:<8.4f}')

    conn.close()


def top_profitable_stocks(limit=20):
    """全市场利润Top股"""
    conn = pymysql.connect(**DB)
    cur = conn.cursor(pymysql.cursors.DictCursor)

    cur.execute("SELECT MAX(report_date) AS max_date FROM financial_quarterly")
    max_date = cur.fetchone()['max_date']

    cur.execute("""
        SELECT
            fq.dm, st.mc, st.zsz,
            fq.roe_ttm, fq.gross_margin, fq.debt_ratio,
            fq.rev_yoy, fq.profit_yoy, fq.eps, fq.bvps
        FROM financial_quarterly fq
        JOIN stock_basic st ON fq.dm = st.dm
        WHERE fq.report_date = %s
          AND fq.roe_ttm IS NOT NULL
          AND st.zsz IS NOT NULL
          AND st.zsz > 50  -- 市值>50亿
        ORDER BY fq.roe_ttm DESC
        LIMIT %s
    """, (max_date, limit))

    print(f'\n=== 全市场 Top {limit} (高ROE + 市值>50亿) ===')
    print(f'{"代码":<8} {"名称":<10} {"市值(亿)":<8} {"ROE%":<8} {"毛利率%":<8} {"营收增%":<8} {"利润增%":<8}')
    for r in cur.fetchall():
        mc = r['mc'][:8] if r['mc'] else ''
        sz = r['zsz'] / 1e8 if r['zsz'] else 0
        print(f'{r["dm"]:<8} {mc:<10} {sz:<8.1f} '
              f'{r["roe_ttm"] or 0:<8.2f} {r["gross_margin"] or 0:<8.2f} '
              f'{r["rev_yoy"] or 0:<8.2f} {r["profit_yoy"] or 0:<8.2f}')

    conn.close()


if __name__ == '__main__':
    import sys
    print('📊 板块强弱分析')
    print('=' * 60)

    analyze_shenwan_top()

    # 看两个具体板块
    print('\n')
    analyze_sector_stocks('sw_dz', 8)  # 电子
    print('\n')
    analyze_sector_stocks('sw_yysw', 8)  # 医药生物

    # 全市场高利润Top
    top_profitable_stocks(15)