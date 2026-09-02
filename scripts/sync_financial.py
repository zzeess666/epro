#!/usr/bin/env python3
"""
财务数据批量同步脚本
- 从麦蕊 API 拉取全市场财务数据
- 支持多线程批量
- 失败重试
- 进度记录到 sync_status
"""
import os
import sys
import time
import requests
import pymysql
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, date
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config.config import MAIRUI_API_KEYS

BASE = 'https://api.mairuiapi.com'
TOKEN = MAIRUI_API_KEYS[0]

DB_CONFIG = {
    'host': '127.0.0.1',
    'port': 3306,
    'user': 'epro',
    'password': 'nTWTkkhfYxnbEhFp',
    'database': 'epro',
    'charset': 'utf8mb4',
}


def safe_decimal(val, default=None):
    """安全转 decimal，'-' 或空值返回 None"""
    if val is None or val == '-' or val == '' or val == '--':
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def safe_date(val):
    """安全转日期"""
    if not val or val == '-' or val == '--':
        return None
    try:
        if len(val) == 8:  # YYYYMMDD
            return datetime.strptime(val, '%Y%m%d').date()
        if len(val) == 10:  # YYYY-MM-DD
            return datetime.strptime(val, '%Y-%m-%d').date()
    except ValueError:
        return None
    return None


def safe_int(val):
    if val is None or val == '-' or val == '' or val == '--':
        return None
    try:
        return int(val)
    except (ValueError, TypeError):
        return None


def fetch_with_retry(url, max_retry=3, timeout=15):
    """带重试的 GET 请求"""
    for i in range(max_retry):
        try:
            r = requests.get(url, timeout=timeout)
            if r.status_code == 200:
                return r.json()
        except Exception as e:
            if i == max_retry - 1:
                print(f'  ! 失败 {url[:80]}: {e}')
                return None
            time.sleep(0.5 * (i + 1))
    return None


def exec_with_retry(func, max_ret=5):
    """带重试执行，处理 deadlock 错误"""
    import pymysql
    for i in range(max_ret):
        try:
            return func()
        except pymysql.err.OperationalError as e:
            if e.args[0] == 1213 and i < max_ret - 1:  # deadlock
                time.sleep(0.1 * (i + 1))
                continue
            raise
        except Exception:
            raise
    return None


def get_all_stocks(conn, skip_existing=None):
    """从 stock_basic 获取所有股票代码（dm + jys）

    skip_existing: 如果指定表名，跳过已入库的股票
    """
    cur = conn.cursor()
    cur.execute("SELECT dm, jys FROM stock_basic")
    rows = cur.fetchall()
    # 转换为代码如 600519.SH
    result = []
    skip_set = set()
    if skip_existing:
        cur.execute(f"SELECT DISTINCT dm FROM {skip_existing}")
        skip_set = {r[0] for r in cur.fetchall()}
        print(f'  已入库 {len(skip_set)} 只，将跳过')

    for dm, jys in rows:
        if not jys or not dm:
            continue
        if dm in skip_set:
            continue
        jys_short = jys.lower()
        result.append((dm, jys_short, f'{dm}.{jys_short.upper()}'))
    return result


# ========== 各表同步函数 ==========

def sync_quarterly(conn, dm_with_jys):
    """同步每股指标（季度）- 批量插入"""
    dm, jys_short, code = dm_with_jys
    et = date.today().strftime('%Y%m%d')
    st = (date.today().replace(year=date.today().year - 5)).strftime('%Y%m%d')

    url = f'{BASE}/hsstock/financial/pershareindex/{code}/{TOKEN}?st={st}&et={et}'
    data = fetch_with_retry(url)
    if not data or not isinstance(data, list):
        return 0

    rows = []
    for item in data:
        report_date = safe_date(str(item.get('jzrq', '')))
        if not report_date:
            continue
        rows.append((
            dm, report_date,
            item.get('report_period'),
            safe_date(str(item.get('plrq', ''))),
            safe_decimal(item.get('jzcsyl')),
            safe_decimal(item.get('zzcsyl')) if 'zzcsyl' in item else None,
            safe_decimal(item.get('xsmlv')),
            safe_decimal(item.get('jlv')),
            safe_decimal(item.get('zcfzl')),
            safe_decimal(item.get('ldbl')) if 'ldbl' in item else None,
            safe_decimal(item.get('zzzhl')) if 'zzzhl' in item else None,
            safe_decimal(item.get('zyyrsrzz')),
            safe_decimal(item.get('jlrzz')),
            safe_decimal(item.get('gsmgsyzzdjlrzz')),
            safe_decimal(item.get('jbmgsy')),
            safe_decimal(item.get('mgjzc')),
            safe_decimal(item.get('mgjyhdxjl')) if 'mgjyhdxjl' in item else None,
        ))

    if not rows:
        return 0

    cur = conn.cursor()
    try:
        cur.executemany("""
            INSERT INTO financial_quarterly
            (dm, report_date, report_period, publish_date,
             roe_ttm, roa_ttm, gross_margin, net_margin, debt_ratio,
             current_ratio, asset_turnover,
             rev_yoy, profit_yoy, eps_yoy,
             eps, bvps, cfps)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON DUPLICATE KEY UPDATE
             publish_date=VALUES(publish_date),
             roe_ttm=VALUES(roe_ttm),
             gross_margin=VALUES(gross_margin),
             net_margin=VALUES(net_margin),
             debt_ratio=VALUES(debt_ratio),
             rev_yoy=VALUES(rev_yoy),
             profit_yoy=VALUES(profit_yoy),
             eps=VALUES(eps),
             bvps=VALUES(bvps)
        """, rows)
        conn.commit()
        return cur.rowcount
    except Exception as e:
        conn.rollback()
        if 'Deadlock' in str(e) or e.args[0] == 1213:
            raise
        print(f'  ! quarterly {dm} err: {str(e)[:200]}', flush=True)
        return 0


def sync_income(conn, dm_with_jys):
    """同步利润表 - 批量插入"""
    dm, jys_short, code = dm_with_jys
    et = date.today().strftime('%Y%m%d')
    st = (date.today().replace(year=date.today().year - 5)).strftime('%Y%m%d')

    url = f'{BASE}/hsstock/financial/income/{code}/{TOKEN}?st={st}&et={et}'
    data = fetch_with_retry(url)
    if not data or not isinstance(data, list):
        return 0

    rows = []
    for item in data:
        report_date = safe_date(str(item.get('jzrq', '')))
        if not report_date:
            continue
        rows.append((
            dm, report_date,
            safe_date(str(item.get('plrq', ''))),
            safe_decimal(item.get('yysr')),
            safe_decimal(item.get('yyzsr')),
            safe_decimal(item.get('yyzcb')),
            safe_decimal(item.get('yycb')),
            safe_decimal(item.get('yylr')),
            safe_decimal(item.get('lrze')),
            safe_decimal(item.get('jlr')),
            safe_decimal(item.get('gsmgsyzzdjlr')),
            safe_decimal(item.get('jlrhfcjcx')),
            safe_decimal(item.get('xsfy')),
            safe_decimal(item.get('glfy')),
            safe_decimal(item.get('yffy')),
            safe_decimal(item.get('cwfy')),
            safe_decimal(item.get('sdsfy')),
            safe_decimal(item.get('jbmgsy')),
            safe_decimal(item.get('xsmgsy')),
        ))

    if not rows:
        return 0

    cur = conn.cursor()
    try:
        cur.executemany("""
            INSERT INTO financial_income
            (dm, report_date, publish_date,
             revenue, total_revenue, total_cost, op_cost,
             op_profit, total_profit, net_profit, parent_net_profit, deduct_net_profit,
             sell_expense, mgr_expense, rd_expense, fin_expense, tax_expense,
             eps, diluted_eps)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON DUPLICATE KEY UPDATE
             publish_date=VALUES(publish_date),
             revenue=VALUES(revenue),
             net_profit=VALUES(net_profit),
             parent_net_profit=VALUES(parent_net_profit)
        """, rows)
        conn.commit()
        return cur.rowcount
    except Exception as e:
        conn.rollback()
        if 'Deadlock' in str(e) or e.args[0] == 1213:
            raise
        return 0


def sync_balance(conn, dm_with_jys):
    """同步资产负债表 - 批量插入"""
    dm, jys_short, code = dm_with_jys
    et = date.today().strftime('%Y%m%d')
    st = (date.today().replace(year=date.today().year - 5)).strftime('%Y%m%d')

    url = f'{BASE}/hsstock/financial/balance/{code}/{TOKEN}?st={st}&et={et}'
    data = fetch_with_retry(url)
    if not data or not isinstance(data, list):
        return 0

    rows = []
    for item in data:
        report_date = safe_date(str(item.get('jzrq', '')))
        if not report_date:
            continue
        rows.append((
            dm, report_date,
            safe_date(str(item.get('plrq', ''))),
            safe_decimal(item.get('zczj')),
            safe_decimal(item.get('fzhj')),
            safe_decimal(item.get('syzqyhj')),
            safe_decimal(item.get('gsmgdqsyhj')),
            safe_decimal(item.get('hbzj')),
            safe_decimal(item.get('yszk')),
            safe_decimal(item.get('ch')),
            safe_decimal(item.get('ldzchj')),
            safe_decimal(item.get('gdzc')),
            safe_decimal(item.get('wxzc')),
            safe_decimal(item.get('sy')),
            safe_decimal(item.get('fldzchj')),
            safe_decimal(item.get('dqjk')),
            safe_decimal(item.get('yfzk')),
            safe_decimal(item.get('cqjk')),
            safe_decimal(item.get('ldfzhj')),
            safe_decimal(item.get('fldfzhj')),
            safe_decimal(item.get('sszb')),
            safe_decimal(item.get('zbgj')),
        ))

    if not rows:
        return 0

    cur = conn.cursor()
    try:
        cur.executemany("""
            INSERT INTO financial_balance
            (dm, report_date, publish_date,
             total_asset, total_liab, equity, parent_equity,
             cash, receivable, inventory, current_asset,
             fixed_asset, intangible_asset, goodwill, noncurrent_asset,
             short_debt, payable, long_debt, current_liab, noncurrent_liab,
             share_capital, capital_reserve)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON DUPLICATE KEY UPDATE
             publish_date=VALUES(publish_date),
             total_asset=VALUES(total_asset),
             total_liab=VALUES(total_liab)
        """, rows)
        conn.commit()
        return cur.rowcount
    except Exception as e:
        conn.rollback()
        if 'Deadlock' in str(e) or e.args[0] == 1213:
            raise
        return 0


def sync_cashflow(conn, dm_with_jys):
    """同步现金流量表 - 批量插入"""
    dm, jys_short, code = dm_with_jys
    et = date.today().strftime('%Y%m%d')
    st = (date.today().replace(year=date.today().year - 5)).strftime('%Y%m%d')

    url = f'{BASE}/hsstock/financial/cashflow/{code}/{TOKEN}?st={st}&et={et}'
    data = fetch_with_retry(url)
    if not data or not isinstance(data, list):
        return 0

    rows = []
    for item in data:
        report_date = safe_date(str(item.get('jzrq', '')))
        if not report_date:
            continue
        rows.append((
            dm, report_date,
            safe_date(str(item.get('plrq', ''))),
            safe_decimal(item.get('jyhdcsdxjlje')),
            safe_decimal(item.get('tzhdcsdxjlxj')),
            safe_decimal(item.get('czhdcsdxjlxj')),
            safe_decimal(item.get('xssptglwsddxj')),
            safe_decimal(item.get('jyhdxjlrxj')),
            safe_decimal(item.get('jyhdxjlcxj')),
            safe_decimal(item.get('tzhdxjlrxj')),
            safe_decimal(item.get('tzhdxjlcxj')),
            safe_decimal(item.get('czhdxjlrxj')),
            safe_decimal(item.get('czhdxjlcxj')),
            safe_decimal(item.get('qmxjjxjdhwye')),
            safe_decimal(item.get('xjxjdhwjzje')),
            safe_decimal(item.get('jlr')),
        ))

    if not rows:
        return 0

    cur = conn.cursor()
    try:
        cur.executemany("""
            INSERT INTO financial_cashflow
            (dm, report_date, publish_date,
             op_cashflow_net, inv_cashflow_net, fin_cashflow_net,
             sale_cash, op_inflow, op_outflow,
             inv_inflow, inv_outflow,
             fin_inflow, fin_outflow,
             end_cash, net_increase, net_profit)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON DUPLICATE KEY UPDATE
             publish_date=VALUES(publish_date),
             op_cashflow_net=VALUES(op_cashflow_net)
        """, rows)
        conn.commit()
        return cur.rowcount
    except Exception as e:
        conn.rollback()
        if 'Deadlock' in str(e) or e.args[0] == 1213:
            raise
        return 0


def sync_hm(conn, dm_with_jys):
    """同步股东户数 - 批量插入"""
    dm, jys_short, code = dm_with_jys
    et = date.today().strftime('%Y%m%d')
    st = (date.today().replace(year=date.today().year - 5)).strftime('%Y%m%d')

    url = f'{BASE}/hsstock/financial/hm/{code}/{TOKEN}?st={st}&et={et}'
    data = fetch_with_retry(url)
    if not data or not isinstance(data, list):
        return 0

    rows = []
    for item in data:
        cutoff = safe_date(str(item.get('jzrq', '')))
        if not cutoff:
            continue
        rows.append((
            dm, cutoff,
            safe_date(str(item.get('plrq', ''))),
            safe_int(item.get('gdzs')),
            safe_int(item.get('agdhs')),
            safe_int(item.get('yltgdhs')),
        ))

    if not rows:
        return 0

    cur = conn.cursor()
    try:
        cur.executemany("""
            INSERT INTO financial_hm
            (dm, cutoff_date, publish_date,
             total_holders, a_holders, float_holders)
            VALUES (%s,%s,%s,%s,%s,%s)
            ON DUPLICATE KEY UPDATE
             publish_date=VALUES(publish_date),
             total_holders=VALUES(total_holders)
        """, rows)
        conn.commit()
        return cur.rowcount
    except Exception as e:
        conn.rollback()
        if 'Deadlock' in str(e) or e.args[0] == 1213:
            raise
        return 0


def sync_dividend(conn, dm_with_jys):
    """同步分红 - 批量插入"""
    dm, jys_short, code = dm_with_jys
    url = f'{BASE}/hscp/jnfh/{dm}/{TOKEN}'
    data = fetch_with_retry(url)
    if not data or not isinstance(data, list):
        return 0

    rows = []
    for item in data:
        declare_date = safe_date(str(item.get('sdate', '')))
        if not declare_date:
            continue
        rows.append((
            dm, declare_date,
            safe_date(str(item.get('cdate', ''))),
            safe_date(str(item.get('edate', ''))),
            safe_decimal(item.get('send')),
            safe_decimal(item.get('give')),
            safe_decimal(item.get('change')),
            item.get('line'),
        ))

    if not rows:
        return 0

    cur = conn.cursor()
    try:
        cur.executemany("""
            INSERT INTO financial_dividend
            (dm, declare_date, ex_date, record_date,
             per_10_share, per_10_send, per_10_transfer, progress)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
            ON DUPLICATE KEY UPDATE
             ex_date=VALUES(ex_date),
             per_10_share=VALUES(per_10_share)
        """, rows)
        conn.commit()
        return cur.rowcount
    except Exception as e:
        conn.rollback()
        if 'Deadlock' in str(e) or e.args[0] == 1213:
            raise
        return 0


def sync_unlock(conn, dm_with_jys):
    """同步解禁 - 批量插入"""
    dm, jys_short, code = dm_with_jys
    url = f'{BASE}/hscp/jjxs/{dm}/{TOKEN}'
    data = fetch_with_retry(url)
    if not data or not isinstance(data, list):
        return 0

    rows = []
    for item in data:
        unlock_date = safe_date(str(item.get('rdate', '')))
        if not unlock_date:
            continue
        rows.append((
            dm, unlock_date,
            safe_date(str(item.get('pdate', ''))),
            safe_int(item.get('ramount')),
            safe_decimal(item.get('rprice')),
            safe_int(item.get('batch')),
        ))

    if not rows:
        return 0

    cur = conn.conn.cursor() if hasattr(conn, 'conn') else conn.cursor()
    try:
        cur.executemany("""
            INSERT INTO financial_unlock
            (dm, unlock_date, publish_date,
             unlock_shares, unlock_value, batch_no)
            VALUES (%s,%s,%s,%s,%s,%s)
            ON DUPLICATE KEY UPDATE
             publish_date=VALUES(publish_date),
             unlock_shares=VALUES(unlock_shares)
        """, rows)
        conn.commit()
        return cur.rowcount
    except Exception as e:
        conn.rollback()
        if 'Deadlock' in str(e) or e.args[0] == 1213:
            raise
        return 0


def sync_top10_holder(conn, dm_with_jys):
    """同步十大股东 - 批量插入"""
    dm, jys_short, code = dm_with_jys
    et = date.today().strftime('%Y%m%d')
    st = (date.today().replace(year=date.today().year - 5)).strftime('%Y%m%d')

    url = f'{BASE}/hsstock/financial/topholder/{code}/{TOKEN}?st={st}&et={et}'
    data = fetch_with_retry(url)
    if not data or not isinstance(data, list):
        return 0

    rows = []
    for item in data:
        cutoff = safe_date(str(item.get('jzrq', '')))
        if not cutoff:
            continue
        rows.append((
            dm, cutoff,
            safe_int(item.get('cgpm')),
            item.get('gdmc'),
            item.get('gdlx'),
            safe_int(item.get('cgsl')),
            safe_decimal(item.get('cgbl')),
        ))

    if not rows:
        return 0

    cur = conn.cursor()
    try:
        cur.executemany("""
            INSERT INTO financial_top10_holder
            (dm, cutoff_date, rank_no, holder_name, holder_type,
             shares, pct)
            VALUES (%s,%s,%s,%s,%s,%s,%s)
            ON DUPLICATE KEY UPDATE
             shares=VALUES(shares),
             pct=VALUES(pct)
        """, rows)
        conn.commit()
        return cur.rowcount
    except Exception as e:
        conn.rollback()
        if 'Deadlock' in str(e) or e.args[0] == 1213:
            raise
        return 0


# ========== 同步编排 ==========

SYNC_FUNCS = {
    'quarterly':    ('财务指标', sync_quarterly),
    'income':       ('利润表',   sync_income),
    'balance':      ('资产负债表', sync_balance),
    'cashflow':     ('现金流量表', sync_cashflow),
    'hm':           ('股东户数', sync_hm),
    'dividend':     ('分红',     sync_dividend),
    'unlock':       ('解禁',     sync_unlock),
    'top10':        ('十大股东', sync_top10_holder),
}


def update_sync_status(conn, data_type, status, records=0, error=None):
    """更新同步状态"""
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO sync_status (data_type, last_run_at, records_synced, status, error_msg)
        VALUES (%s, NOW(), %s, %s, %s)
        ON DUPLICATE KEY UPDATE
         last_run_at=NOW(),
         records_synced=VALUES(records_synced),
         status=VALUES(status),
         error_msg=VALUES(error_msg)
    """, (data_type, records, status, error))
    conn.commit()


def sync_all(stock_list, data_types, max_workers=1):
    """同步指定数据类型（顺序执行避免死锁）"""
    conn = pymysql.connect(**DB_CONFIG)

    for dt in data_types:
        if dt not in SYNC_FUNCS:
            print(f'未知数据类型: {dt}')
            continue

        name, func = SYNC_FUNCS[dt]
        print(f'\n=== 同步 {name} ({len(stock_list)}只) ===')

        total = 0
        success = 0
        failed = 0
        t0 = time.time()

        for i, s in enumerate(stock_list, 1):
            try:
                r = exec_with_retry(lambda: func(conn, s))
                if r and r > 0:
                    success += 1
                    total += r
                else:
                    failed += 1
            except Exception as e:
                failed += 1

            if i % 100 == 0:
                elapsed = time.time() - t0
                rate = i / elapsed
                remaining = (len(stock_list) - i) / rate
                print(f'  {i}/{len(stock_list)} 成功{success} 失败{failed} 已入库{total} 速度{rate:.1f}/秒 剩余{remaining:.0f}秒', flush=True)
            elif i % 20 == 0:
                # 每 20 只打印当前 dm，定位卡在哪
                print(f'    [{i}] {s[0]}', flush=True)

        elapsed = time.time() - t0
        status = 'success' if failed < len(stock_list) * 0.1 else 'partial'
        update_sync_status(conn, dt, status, records=total)
        print(f'  完成: 成功{success} 失败{failed} 入库{total}条 耗时{elapsed:.0f}秒')

    conn.close()


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--types', nargs='+', default=['quarterly'],
                       choices=list(SYNC_FUNCS.keys()),
                       help='同步的数据类型')
    parser.add_argument('--workers', type=int, default=4)
    args = parser.parse_args()

    conn = pymysql.connect(**DB_CONFIG)
    stock_list = get_all_stocks(conn, skip_existing='financial_quarterly' if 'quarterly' in args.types else None)
    conn.close()

    print(f'共 {len(stock_list)} 只股票，开始同步 {args.types}')
    sync_all(stock_list, args.types, args.workers)