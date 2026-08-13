"""回溯引擎：读历史 K 线模拟持有 N 天（含止损），纯本地计算。"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Optional

from src.db.connection import get_connection
from src.strategy import iter_strategies
from src.strategy.base_strategy import ensure_tables, load_klines, load_stock_codes

DEFAULT_HOLD_DAYS = 5


def _round2(value: float) -> float:
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _simulate_hold(
    klines: list[dict[str, Any]],
    entry_index: int,
    entry_price: float,
    stop_loss: float,
    hold_days: int,
) -> Optional[float]:
    """
    从信号日收盘买入，持有 hold_days 个交易日。
    期间最低价跌破止损 → 按止损价计算亏损；否则按第 N 日收盘价计算收益。
    未来 K 线不足则跳过。
    """
    if entry_price <= 0:
        return None
    exit_index = entry_index + hold_days
    if exit_index >= len(klines):
        return None

    for j in range(entry_index + 1, exit_index + 1):
        low = klines[j]["l"]
        if low is not None and low <= stop_loss:
            return (stop_loss - entry_price) / entry_price * 100.0

    exit_close = klines[exit_index]["c"]
    if exit_close is None:
        return None
    return (exit_close - entry_price) / entry_price * 100.0


def _date_range(klines_map: dict[str, list[dict[str, Any]]]) -> tuple[Optional[date], Optional[date]]:
    start: Optional[date] = None
    end: Optional[date] = None
    for rows in klines_map.values():
        if not rows:
            continue
        first, last = rows[0]["t"], rows[-1]["t"]
        if first is not None and (start is None or first < start):
            start = first
        if last is not None and (end is None or last > end):
            end = last
    return start, end


def backtest_strategy(
    strategy_name: str,
    klines_map: dict[str, list[dict[str, Any]]],
    hold_days: int,
) -> dict[str, Any]:
    strategy = iter_strategies(strategy_name)[0]
    returns: list[float] = []

    for dm, klines in klines_map.items():
        if len(klines) < strategy.min_bars + hold_days:
            continue
        start = max(strategy.min_bars - 1, 0)
        last_entry = len(klines) - hold_days - 1
        for index in range(start, last_entry + 1):
            signal = strategy.evaluate(dm, klines, index)
            if signal is None:
                continue
            ret = _simulate_hold(
                klines,
                index,
                signal.entry_price,
                signal.stop_loss,
                hold_days,
            )
            if ret is None:
                continue
            returns.append(ret)

    start_date, end_date = _date_range(klines_map)
    sample_count = len(returns)
    wins = [r for r in returns if r > 0]
    losses = [r for r in returns if r <= 0]
    win_count = len(wins)
    win_rate = (win_count / sample_count * 100.0) if sample_count else 0.0
    avg_return = (sum(wins) / len(wins)) if wins else 0.0
    avg_loss = (sum(losses) / len(losses)) if losses else 0.0

    return {
        "strategy": strategy.name,
        "start_date": start_date,
        "end_date": end_date,
        "hold_days": hold_days,
        "sample_count": sample_count,
        "win_count": win_count,
        "win_rate": _round2(win_rate),
        "avg_return": _round2(avg_return),
        "avg_loss": _round2(avg_loss),
    }


def save_result(row: dict[str, Any]) -> None:
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO backtest_result
                  (strategy, start_date, end_date, hold_days,
                   sample_count, win_count, win_rate, avg_return, avg_loss)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    row["strategy"],
                    row["start_date"],
                    row["end_date"],
                    row["hold_days"],
                    row["sample_count"],
                    row["win_count"],
                    row["win_rate"],
                    row["avg_return"],
                    row["avg_loss"],
                ),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def run(
    strategy_code: str | None = None,
    hold_days: int = DEFAULT_HOLD_DAYS,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    if hold_days <= 0:
        raise ValueError("hold_days 必须为正整数")

    ensure_tables()
    codes = load_stock_codes(limit)
    strategies = iter_strategies(strategy_code)
    if not codes:
        print("[backtest] stock_basic 为空，请先完成 M1 同步")
        results = []
        for s in strategies:
            row = {
                "strategy": s.name,
                "start_date": None,
                "end_date": None,
                "hold_days": hold_days,
                "sample_count": 0,
                "win_count": 0,
                "win_rate": 0.0,
                "avg_return": 0.0,
                "avg_loss": 0.0,
            }
            save_result(row)
            results.append(row)
        return results

    print(f"[backtest] 加载 K 线 股票={len(codes)} hold_days={hold_days}")
    klines_map: dict[str, list[dict[str, Any]]] = {}
    for i, dm in enumerate(codes, start=1):
        klines_map[dm] = load_klines(dm)
        if i % 10 == 0 or i == len(codes):
            print(f"[backtest] 读取进度 {i}/{len(codes)}")

    results: list[dict[str, Any]] = []
    for strategy in strategies:
        print(f"[backtest] 回溯策略 {strategy.name} ...")
        row = backtest_strategy(strategy.name, klines_map, hold_days)
        save_result(row)
        results.append(row)
        print(
            f"[backtest] {strategy.name} 样本={row['sample_count']} "
            f"胜={row['win_count']} 胜率={row['win_rate']}% "
            f"均盈={row['avg_return']}% 均亏={row['avg_loss']}%"
        )
    return results
