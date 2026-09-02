#!/usr/bin/env python3
"""
全市场财务数据多线程批量同步
- 8 个线程并行
- 每类表单独运行
- 进度可视化
"""
import os
import sys
import time
import pymysql
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts.sync_financial import (
    sync_quarterly, sync_income, sync_balance, sync_cashflow,
    sync_hm, sync_dividend, sync_unlock, sync_top10_holder,
    get_all_stocks, DB_CONFIG, SYNC_FUNCS, update_sync_status
)


def run_one_type(data_type, max_workers=8):
    """运行单个数据类型的同步"""
    name, func = SYNC_FUNCS[data_type]

    # 每个线程独立的 DB 连接
    thread_local = {}

    def get_thread_conn():
        tid = os.getpid() + threading.current_thread().ident
        if tid not in thread_local:
            thread_local[tid] = pymysql.connect(**DB_CONFIG)
        return thread_local[tid]

    # 主连接获取股票列表
    conn = pymysql.connect(**DB_CONFIG)
    stocks = get_all_stocks(conn)
    conn.close()

    print(f'\n=== {name} ({len(stocks)}只) ===')
    t0 = time.time()

    success = 0
    failed = 0
    total_records = 0

    def worker(stock):
        try:
            c = get_thread_conn()
            return func(c, stock)
        except Exception as e:
            return 0

    import threading

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(worker, s): s for s in stocks}
        for i, f in enumerate(as_completed(futures), 1):
            try:
                r = f.result(timeout=30)
                if r > 0:
                    success += 1
                    total_records += r
                else:
                    failed += 1
            except Exception:
                failed += 1
            if i % 500 == 0:
                elapsed = time.time() - t0
                rate = i / elapsed
                remaining = (len(stocks) - i) / rate
                print(f'  {i}/{len(stocks)} 成功{success} 失败{failed} 已入库{total_records} 速度{rate:.1f}/秒 剩余{remaining:.0f}秒')

    elapsed = time.time() - t0
    print(f'  完成: 成功{success} 失败{failed} 入库{total_records}条 耗时{elapsed:.0f}秒')

    # 清理线程连接
    for c in thread_local.values():
        try:
            c.close()
        except:
            pass

    # 写状态
    conn = pymysql.connect(**DB_CONFIG)
    status = 'success' if failed < len(stocks) * 0.05 else 'partial'
    update_sync_status(conn, data_type, status, records=total_records)
    conn.close()


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--types', nargs='+', default=['quarterly'],
                       choices=list(SYNC_FUNCS.keys()))
    parser.add_argument('--workers', type=int, default=8)
    args = parser.parse_args()

    print(f'开始同步 {args.types}, 线程数 {args.workers}')
    for dt in args.types:
        run_one_type(dt, args.workers)
    print('\n全部完成')