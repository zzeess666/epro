"""本地计算 MA5/MA10/MA20/MA60，回写 daily_kline。不调用麦蕊均线接口。"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from config.config import SYNC_STOCK_LIMIT
from src.db.connection import get_connection

MA_WINDOWS = (5, 10, 20, 60)


def _round2(value: float) -> float:
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def moving_averages(closes: list[Optional[float]]) -> dict[int, list[Optional[float]]]:
    """按日期升序的收盘价计算各窗口均线；样本不足则为 None。"""
    result: dict[int, list[Optional[float]]] = {w: [None] * len(closes) for w in MA_WINDOWS}
    running: list[float] = []
    for i, close in enumerate(closes):
        if close is None:
            continue
        running.append(float(close))
        for window in MA_WINDOWS:
            if len(running) >= window:
                window_slice = running[-window:]
                result[window][i] = _round2(sum(window_slice) / window)
    return result


def _load_codes(limit: int) -> list[str]:
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT dm
                FROM stock_basic
                ORDER BY dm
                LIMIT %s
                """,
                (limit,),
            )
            return [row["dm"] for row in cursor.fetchall()]
    finally:
        conn.close()


def _load_klines(dm: str) -> list[dict]:
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT t, c
                FROM daily_kline
                WHERE dm = %s
                ORDER BY t ASC
                """,
                (dm,),
            )
            return list(cursor.fetchall())
    finally:
        conn.close()


def _update_ma(dm: str, rows: list[dict], ma_map: dict[int, list[Optional[float]]]) -> int:
    payload = [
        (
            ma_map[5][i],
            ma_map[10][i],
            ma_map[20][i],
            ma_map[60][i],
            dm,
            rows[i]["t"],
        )
        for i in range(len(rows))
    ]
    if not payload:
        return 0
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.executemany(
                """
                UPDATE daily_kline
                SET ma5 = %s, ma10 = %s, ma20 = %s, ma60 = %s
                WHERE dm = %s AND t = %s
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


def run(limit: int | None = None) -> int:
    cap = SYNC_STOCK_LIMIT if limit is None else min(int(limit), SYNC_STOCK_LIMIT)
    codes = _load_codes(cap)
    if not codes:
        print("[indicator] stock_basic 为空，请先运行 sync_stock_list")
        return 0

    updated_stocks = 0
    updated_rows = 0
    print(f"[indicator] 开始计算 MA，股票数={len(codes)}")

    for index, dm in enumerate(codes, start=1):
        rows = _load_klines(dm)
        if not rows:
            continue
        closes = [None if row["c"] is None else float(row["c"]) for row in rows]
        ma_map = moving_averages(closes)
        updated_rows += _update_ma(dm, rows, ma_map)
        updated_stocks += 1
        if index % 10 == 0 or index == len(codes):
            print(f"[indicator] 进度 {index}/{len(codes)} 已回写行={updated_rows}")

    print(f"[indicator] 完成，股票={updated_stocks} 行={updated_rows}")
    return updated_rows


if __name__ == "__main__":
    run()
