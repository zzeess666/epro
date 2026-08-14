"""同步日K：仅处理 stock_basic 中不超过 100 只股票的近 120 个交易日。"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Optional

from config.config import SYNC_STOCK_LIMIT
from src.api.mairui_client import MairuiClient
from src.db.connection import get_connection

KLINE_LIMIT_INIT = 3000   # 初始化：一次拉全历史（覆盖上市以来全部K线）
KLINE_LIMIT_DAILY = 30    # 日常：增量最近30交易日
INIT_START = "20150101"   # 初始化起始日期（足够早）
DAILY_BUFFER_DAYS = 45    # 日常往前缓冲自然日（约30交易日）


def _to_date_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip().replace("/", "-")
    if not text:
        return None
    compact = text.replace("-", "")
    if len(compact) >= 8 and compact[:8].isdigit():
        y, m, d = compact[:4], compact[4:6], compact[6:8]
        return f"{y}-{m}-{d}"
    return None


def _to_decimal(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value: Any) -> Optional[int]:
    num = _to_decimal(value)
    if num is None:
        return None
    return int(num)


def _load_stocks(limit: int) -> list[dict[str, str]]:
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT dm, jys
                FROM stock_basic
                ORDER BY dm
                LIMIT %s
                """,
                (limit,),
            )
            return list(cursor.fetchall())
    finally:
        conn.close()


def _upsert_klines(dm: str, rows: list[dict[str, Any]]) -> int:
    payload = []
    for row in rows:
        trade_date = _to_date_str(row.get("t"))
        if not trade_date:
            continue
        payload.append(
            (
                dm,
                trade_date,
                _to_decimal(row.get("o")),
                _to_decimal(row.get("h")),
                _to_decimal(row.get("l")),
                _to_decimal(row.get("c")),
                _to_int(row.get("v")),
                _to_decimal(row.get("a")),
                _to_decimal(row.get("pc")),
            )
        )
    if not payload:
        return 0

    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.executemany(
                """
                REPLACE INTO daily_kline (dm, t, o, h, l, c, v, a, pc)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                payload,
            )
        conn.commit()
        return len(payload)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def run(limit: int | None = None, init: bool = False) -> int:
    cap = SYNC_STOCK_LIMIT if limit is None else min(int(limit), SYNC_STOCK_LIMIT)
    stocks = _load_stocks(cap)
    if not stocks:
        print("[daily_kline] stock_basic 为空，请先运行 sync_stock_list")
        return 0

    end = date.today()
    kline_limit = KLINE_LIMIT_INIT if init else KLINE_LIMIT_DAILY
    if init:
        start = date(2015, 1, 1)
    else:
        start = end - timedelta(days=DAILY_BUFFER_DAYS)
    client = MairuiClient()
    total_rows = 0
    failed = 0

    print(
        f"[daily_kline] 开始同步 {len(stocks)} 只，"
        f"模式={'初始化全历史' if init else '日常增量'} "
        f"区间 {start.isoformat()} ~ {end.isoformat()}，lt={kline_limit}"
    )

    for index, stock in enumerate(stocks, start=1):
        dm = stock["dm"]
        jys = stock.get("jys") or ""
        try:
            rows = client.get_daily_kline(
                code=dm,
                jys=jys,
                start=start.strftime("%Y%m%d"),
                end=end.strftime("%Y%m%d"),
                limit=kline_limit,
            )
            written = _upsert_klines(dm, rows)
            total_rows += written
        except Exception as exc:
            failed += 1
            print(f"[daily_kline] {dm}.{jys} 失败: {exc}")

        if index % 10 == 0 or index == len(stocks):
            print(
                f"[daily_kline] 进度 {index}/{len(stocks)} "
                f"累计K线={total_rows} 失败={failed}"
            )

    print(f"[daily_kline] 完成，入库 {total_rows} 条，失败 {failed} 只")
    return total_rows


if __name__ == "__main__":
    run()
