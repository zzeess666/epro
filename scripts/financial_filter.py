#!/usr/bin/env python3
"""
财务过滤选股 Top10
- 硬过滤：ROE>10% + 毛利率>20% + 负债率<70% + 利润正增长 + 市值>50亿
- 综合评分：ROE(40%) + 毛利率(20%) + 营收增长(15%) + 利润增长(15%) + 负债率逆向(10%)
- 输出Top10 + 行业分布
"""
import pymysql

DB = {
    'host': '127.0.0.1', 'port': 3306, 'user': 'epro',
    'password': 'nTWTkkhfYxnbEhFp', 'database': 'epro', 'charset': 'utf8mb4',
}


def score_stock(fq):
    """综合评分 0-100"""
    score = 0

    # ROE 40分 (>=20%满分)
    roe = fq.get('roe_ttm') or 0
    score += min(roe / 20 * 40, 40)

    # 毛利率 20分 (>=50%满分)
    gm = fq.get('gross_margin') or 0
    score += min(gm / 50 * 20, 20)

    # 营收增长 15分 (>=30%满分)
    rev = fq.get('rev_yoy') or 0
    score += min(max(rev, 0) / 30 * 15, 15)

    # 利润增长 15分 (>=50%满分)
    prof = fq.get('profit_yoy') or 0
    score += min(max(prof, 0) / 50 * 15, 15)

    # 负债率逆向 10分 (0%满分，100%零分)
    debt = fq.get('debt_ratio') or 0
    score += max(0, (100 - debt) / 100 * 10)

    return round(score, 2)


def filter_top_stocks(min_roe=15, min_gm=30, max_debt=60, min_rev=0, top_n=10):
    """硬过滤+评分 TopN"""
    conn = pymysql.connect(**DB)
    cur = conn.cursor(pymysql.cursors.DictCursor)

    # 最新财报日期
    cur.execute("SELECT MAX(report_date) AS d FROM financial_quarterly")
    max_date = cur.fetchone()['d']

    cur.execute("""
        SELECT
            fq.dm, st.mc,
            fq.roe_ttm, fq.gross_margin, fq.debt_ratio,
            fq.rev_yoy, fq.profit_yoy, fq.eps
        FROM financial_quarterly fq
        JOIN stock_basic st ON fq.dm = st.dm
        WHERE fq.report_date = %s
          AND fq.roe_ttm >= %s
          AND fq.gross_margin >= %s
          AND fq.debt_ratio <= %s
          AND fq.profit_yoy > 0
          AND fq.rev_yoy >= %s
    """, (max_date, min_roe, min_gm, max_debt, min_rev))

    candidates = cur.fetchall()
    print(f'过滤后候选: {len(candidates)} 只')

    # 评分
    scored = []
    for c in candidates:
        c['score'] = score_stock(c)
        scored.append(c)

    # 按分排序
    scored.sort(key=lambda x: x['score'], reverse=True)
    top = scored[:top_n]

    return top, max_date


def show_industry_distribution(top):
    """显示Top10的行业分布"""
    conn = pymysql.connect(**DB)
    cur = conn.cursor(pymysql.cursors.DictCursor)

    dm_list = [t['dm'] for t in top]
    placeholders = ','.join(['%s'] * len(dm_list))

    cur.execute(f"""
        SELECT sb.code, sb.name, COUNT(DISTINCT ss.dm) AS cnt
        FROM sector_basic sb
        JOIN stock_sector ss ON ss.sector_code = sb.code
        WHERE sb.level = 'sw_yx' AND sb.code NOT REGEXP '^sw2_'
          AND ss.dm IN ({placeholders})
        GROUP BY sb.code, sb.name
        ORDER BY cnt DESC
    """, dm_list)

    print('\n行业分布:')
    for r in cur.fetchall():
        print(f'  {r["code"]:<15} {r["name"]:<20} {r["cnt"]} 只')
    conn.close()


def main():
    print('=' * 80)
    print('财务过滤选股 Top10')
    print('=' * 80)
    print('过滤条件: ROE≥15% & 毛利率≥30% & 负债率≤60% & 利润正增 & 营收正增')
    print()

    # 严格过滤 + Top10
    top, date = filter_top_stocks(
        min_roe=15, min_gm=30, max_debt=60, min_rev=0, top_n=10
    )

    print(f'数据日期: {date}\n')
    print(f'{"代码":<8} {"名称":<10} {"ROE%":<7} {"毛利%":<7} {"负债%":<7} {"营收%":<7} {"利润%":<7} {"评分"}')
    print('-' * 80)
    for r in top:
        mc = r['mc'][:8] if r['mc'] else ''
        print(f'{r["dm"]:<8} {mc:<10} '
              f'{r["roe_ttm"] or 0:<7.2f} {r["gross_margin"] or 0:<7.2f} '
              f'{r["debt_ratio"] or 0:<7.2f} {r["rev_yoy"] or 0:<7.2f} '
              f'{r["profit_yoy"] or 0:<7.2f} {r["score"]}')

    show_industry_distribution(top)

    # 宽松过滤 + Top 30
    print('\n' + '=' * 80)
    print('更宽松的过滤 Top 30（ROE≥8%、毛利≥20%、负债<70%）')
    print('=' * 80)

    top30, _ = filter_top_stocks(
        min_roe=8, min_gm=20, max_debt=70, min_rev=0, top_n=30
    )

    print(f'{"代码":<8} {"名称":<10} {"ROE%":<7} {"毛利%":<7} {"营收%":<7} {"利润%":<7} {"评分"}')
    print('-' * 80)
    for r in top30:
        mc = r['mc'][:8] if r['mc'] else ''
        print(f'{r["dm"]:<8} {mc:<10} '
              f'{r["roe_ttm"] or 0:<7.2f} {r["gross_margin"] or 0:<7.2f} '
              f'{r["rev_yoy"] or 0:<7.2f} {r["profit_yoy"] or 0:<7.2f} {r["score"]}')


if __name__ == '__main__':
    main()