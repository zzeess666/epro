#!/usr/bin/env python3
"""
财务+技术叠加精选脚本
- 输入：财务过滤 Top N（财务_quarterly 最新季报）
- 叠加：当日技术因子命中（factor_flag 最新日）
- 叠加：大盘 MA20 过滤（index_kline）
- 输出：今日可买股票 + 行业分布 + 综合评分
"""
import sys
import os
import pymysql
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DB = {
    'host': '127.0.0.1', 'port': 3306, 'user': 'epro',
    'password': 'nTWTkkhfYxnbEhFp', 'database': 'epro', 'charset': 'utf8mb4',
}


def get_market_status(conn):
    """大盘 MA20 状态（多指数）"""
    cur = conn.cursor(pymysql.cursors.DictCursor)
    cur.execute("""
        SELECT code, c, ma20,
               CASE WHEN c > ma20 THEN 1 ELSE 0 END AS bull
        FROM index_kline
        WHERE t = (SELECT MAX(t) FROM index_kline)
          AND code IN ('000001.SH','399001.SZ','000688.SH','399006.SZ')
    """)
    rows = {r['code']: r for r in cur.fetchall()}
    bull_count = sum(r['bull'] for r in rows.values())
    return rows, bull_count


def get_factor_stocks(conn, factor_date, factors=None):
    """某日所有满足任一/所有指定因子的股票集合"""
    cur = conn.cursor()
    if factors is None:
        factors = ['box_breakout', 'second_breakout', 'macd_golden',
                   'expma_golden', 'gap_up', 'one_yang_3ma', 'ma_bull',
                   'ma5_cross_10', 'shrink_pullback', 'new_high_20', 'limit_up']
    placeholders = ','.join(['%s'] * len(factors))
    cur.execute(f"""
        SELECT dm, factor
        FROM factor_flag
        WHERE t = %s AND flag = 1 AND factor IN ({placeholders})
    """, [factor_date] + factors)
    rows = cur.fetchall()

    # 每个股票的因子命中数
    factor_count = {}
    factor_list = {}
    for dm, factor in rows:
        factor_count[dm] = factor_count.get(dm, 0) + 1
        factor_list.setdefault(dm, []).append(factor)
    return factor_count, factor_list


def get_financial_candidates(conn, min_roe, min_gm, max_debt):
    """财务硬过滤候选"""
    cur = conn.cursor(pymysql.cursors.DictCursor)
    cur.execute("SELECT MAX(report_date) AS d FROM financial_quarterly")
    financial_date = cur.fetchone()['d']

    cur.execute("""
        SELECT fq.dm, st.mc,
               fq.roe_ttm, fq.gross_margin, fq.debt_ratio,
               fq.rev_yoy, fq.profit_yoy, fq.eps
        FROM financial_quarterly fq
        JOIN stock_basic st ON fq.dm = st.dm
        WHERE fq.report_date = %s
          AND fq.roe_ttm >= %s
          AND fq.gross_margin >= %s
          AND fq.debt_ratio <= %s
          AND fq.profit_yoy > 0
          AND fq.rev_yoy > 0
    """, (financial_date, min_roe, min_gm, max_debt))
    return cur.fetchall(), financial_date


def score_combo(stock, factor_count, factor_list):
    """综合评分 = 财务得分*0.6 + 技术得分*0.4"""
    # 财务得分（复用 financial_filter 的逻辑）
    s = 0
    roe = stock.get('roe_ttm') or 0
    s += min(roe / 20 * 40, 40)
    gm = stock.get('gross_margin') or 0
    s += min(gm / 50 * 20, 20)
    rev = stock.get('rev_yoy') or 0
    s += min(max(rev, 0) / 30 * 15, 15)
    prof = stock.get('profit_yoy') or 0
    s += min(max(prof, 0) / 50 * 15, 15)
    debt = stock.get('debt_ratio') or 0
    s += max(0, (100 - debt) / 100 * 10)
    fin_score = round(s, 2)

    # 技术得分：每个因子命中 +10 分
    fc = factor_count.get(stock['dm'], 0)
    tech_score = min(fc * 10, 50)

    combined = round(fin_score * 0.6 + tech_score * 0.8, 2)
    return combined, fin_score, tech_score, fc, factor_list.get(stock['dm'], [])


def main(min_roe=15, min_gm=30, max_debt=60, min_factors=2, top_n=10):
    conn = pymysql.connect(**DB)
    print('=' * 80)
    print('财务+技术叠加精选')
    print('=' * 80)
    print(f'财务过滤: ROE≥{min_roe}% 毛利≥{min_gm}% 负债≤{max_debt}%')
    print(f'技术要求: 命中 ≥ {min_factors} 个技术因子')

    # 大盘
    indexes, bull_count = get_market_status(conn)
    print(f'\n大盘指数: {bull_count}/4 站上MA20')
    for code, r in indexes.items():
        marker = '✅' if r['bull'] else '❌'
        print(f'  {marker} {code}: 现{r["c"]:.2f} MA20={r["ma20"]:.2f}')

    if bull_count < 2:
        print('\n⚠大盘偏弱，建议降低仓位或观望')

    # 财务候选
    candidates, fin_date = get_financial_candidates(conn, min_roe, min_gm, max_debt)
    print(f'\n财务候选: {len(candidates)} 只 (季报日期: {fin_date})')

    # 最新因子日期
    cur = conn.cursor()
    cur.execute("SELECT MAX(t) FROM factor_flag")
    factor_date = cur.fetchone()[0]
    print(f'因子日期: {factor_date}')

    # 因子命中
    factor_count, factor_list = get_factor_stocks(conn, factor_date)
    print(f'今日有因子命中的股票: {len(factor_count)} 只')

    # 叠加：要求每个候选股票至少命中 N 个因子
    scored = []
    for s in candidates:
        combined, fin_score, tech_score, fc, factors = score_combo(s, factor_count, factor_list)
        if fc < min_factors:
            continue
        s['combined_score'] = combined
        s['fin_score'] = fin_score
        s['tech_score'] = tech_score
        s['factor_count'] = fc
        s['factors'] = factors
        scored.append(s)

    scored.sort(key=lambda x: x['combined_score'], reverse=True)
    top = scored[:top_n]

    print(f'\n今日精选: {len(top)} 只 (候选{len(scored)}只满足最少{min_factors}因子)\n')
    print(f'{"代码":<8} {"名称":<10} {"财务分":<7} {"技术分":<7} {"因子":<5} {"ROE%":<6} {"毛利%":<6} {"利润%":<7} {"综合"}')
    print('-' * 80)
    for r in top:
        mc = r['mc'][:8] if r['mc'] else ''
        print(f'{r["dm"]:<8} {mc:<10} {r["fin_score"]:<7.2f} {r["tech_score"]:<7.2f} '
              f'{r["factor_count"]:<5} {r["roe_ttm"] or 0:<6.2f} {r["gross_margin"] or 0:<6.2f} '
              f'{r["profit_yoy"] or 0:<7.2f} {r["combined_score"]}')

    # 显示每个股票的因子明细
    print('\n因子明细:')
    factor_cn = {
        'box_breakout': '箱体突破', 'second_breakout': '二次突破',
        'macd_golden': 'MACD金叉', 'expma_golden': 'EXPMA金叉',
        'gap_up': '跳空高开', 'one_yang_3ma': '一阳穿三线',
        'ma_bull': '多头排列', 'ma5_cross_10': '5穿10日',
        'shrink_pullback': '缩量回踩', 'new_high_20': '20日新高',
        'limit_up': '涨停', 'volume_ratio_high': '放量',
        'kline_reversal': 'K线反转', 'above_ma20': '站上20日线'
    }
    for r in top:
        factors_str = ', '.join([factor_cn.get(f, f) for f in r['factors']])
        print(f'  {r["dm"]} {r["mc"][:8]:<8} ({r["factor_count"]}因子) {factors_str}')

    conn.close()
    return top


if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('--min-roe', type=float, default=15)
    p.add_argument('--min-gm', type=float, default=30)
    p.add_argument('--max-debt', type=float, default=60)
    p.add_argument('--min-factors', type=int, default=2)
    p.add_argument('--top', type=int, default=10)
    args = p.parse_args()
    main(args.min_roe, args.min_gm, args.max_debt, args.min_factors, args.top)