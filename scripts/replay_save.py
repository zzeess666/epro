#!/usr/bin/env python3
"""CLI：预计算最优组合测试期历史选股，写入 history_replay。

信号日 → _find_pullback_entry 回踩买入 → 持有；只用库内数据。
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.combo.combination_miner import (
    PERIODS,
    _find_pullback_entry,
    is_market_bull,
    load_index_bull_map,
    load_tradable_codes,
    load_trade_dates,
    split_train_test,
)
from src.db.connection import get_connection
from src.factor.factor_library import load_klines, parse_combo
from src.screen.dynamic_screener import load_best_combo
from src.strategy.base_strategy import to_date, to_float

_CREATE_HISTORY_REPLAY = """
CREATE TABLE IF NOT EXISTS history_replay (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  combo VARCHAR(200) COMMENT '组合名',
  period VARCHAR(10) COMMENT '周期标签',
  dm VARCHAR(10) COMMENT '股票代码',
  mc VARCHAR(50) COMMENT '股票名称',
  buy_date DATE COMMENT '买入日',
  entry DECIMAL(10,2) COMMENT '买入价',
  stop DECIMAL(10,2) COMMENT '止损价',
  exit_price DECIMAL(10,2) COMMENT '出场价',
  ret DECIMAL(10,2) COMMENT '收益率%',
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  KEY idx_combo (combo, period)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
"""


def ensure_tables() -> None:
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(_CREATE_HISTORY_REPLAY)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _round2(value: float) -> float:
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _period_spec(period: str):
    for spec in PERIODS:
        if spec.period == period:
            return spec
    return None


def _simulate_hold(
    klines: list[dict[str, Any]],
    entry_index: int,
    entry_price: float,
    hold_days: int,
    stop_pct: float,
) -> Optional[tuple[float, float]]:
    """持有 hold_days，触及止损则按止损价出场。K 线不足返回 None。"""
    if entry_price <= 0:
        return None
    n = len(klines)
    exit_index = entry_index + hold_days
    if exit_index >= n:
        return None
    stop = entry_price * (1.0 - stop_pct)
    for j in range(entry_index + 1, exit_index + 1):
        low = klines[j].get("l")
        if low is not None and float(low) <= stop:
            return stop, (stop - entry_price) / entry_price * 100.0
    exit_close = klines[exit_index].get("c")
    if exit_close is None:
        return None
    exit_price = float(exit_close)
    return exit_price, (exit_price - entry_price) / entry_price * 100.0


def collect_records(
    combo: str,
    period: str,
    hold_days: int,
    stop_pct: float,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    factors = parse_combo(combo)
    if not factors:
        print("[replay] 组合名为空，无法回放")
        return []

    dates = load_trade_dates()
    _, test_dates = split_train_test(dates)
    codes = load_tradable_codes(limit)
    bull_map = load_index_bull_map()
    factor_list = list(factors)
    target = set(factors)
    placeholders = ",".join(["%s"] * len(factor_list))

    print(
        f"[replay] 组合={combo} 周期={period}({hold_days}日) 止损={stop_pct * 100:.1f}% "
        f"股票={len(codes)} 测试日={len(test_dates)}"
    )
    if not codes:
        print("[replay] 无可用股票（需沪深非 ST）")
        return []
    if not test_dates:
        print("[replay] 交易日不足以切分测试期")
        return []

    conn = get_connection()
    records: list[dict[str, Any]] = []
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT dm, mc FROM stock_basic")
            name_map = {row["dm"]: str(row.get("mc") or "") for row in cursor.fetchall()}
            for index, dm in enumerate(codes, start=1):
                cursor.execute(
                    f"""
                    SELECT t, factor
                    FROM factor_flag
                    WHERE dm = %s AND flag = 1 AND factor IN ({placeholders})
                    """,
                    (dm, *factor_list),
                )
                flags_by_date: dict = defaultdict(set)
                for row in cursor.fetchall():
                    day = to_date(row["t"])
                    factor = str(row["factor"] or "").strip()
                    if day is None or not factor:
                        continue
                    flags_by_date[day].add(factor)
                if not flags_by_date:
                    if index % 50 == 0 or index == len(codes):
                        print(f"[replay] 进度 {index}/{len(codes)} 记录={len(records)}")
                    continue
                klines = load_klines(dm, cursor)
                date_to_index = {
                    bar["t"]: i for i, bar in enumerate(klines) if bar["t"] is not None
                }
                for day, hit_factors in flags_by_date.items():
                    if not target.issubset(hit_factors):
                        continue
                    if day not in test_dates:
                        continue
                    if not is_market_bull(dm, day, bull_map):
                        continue
                    signal_index = date_to_index.get(day)
                    if signal_index is None:
                        continue
                    entry_index = _find_pullback_entry(klines, signal_index)
                    if entry_index is None:
                        continue
                    close = klines[entry_index].get("c")
                    if close is None or float(close) <= 0:
                        continue
                    entry_price = float(close)
                    sim = _simulate_hold(
                        klines, entry_index, entry_price, hold_days, stop_pct
                    )
                    if sim is None:
                        continue
                    exit_price, ret = sim
                    buy_date = klines[entry_index]["t"]
                    records.append(
                        {
                            "combo": combo,
                            "period": period,
                            "dm": dm,
                            "mc": name_map.get(dm, ""),
                            "buy_date": buy_date,
                            "entry": _round2(entry_price),
                            "stop": _round2(entry_price * (1.0 - stop_pct)),
                            "exit_price": _round2(exit_price),
                            "ret": _round2(ret),
                        }
                    )
                if index % 50 == 0 or index == len(codes):
                    print(f"[replay] 进度 {index}/{len(codes)} 记录={len(records)}")
    finally:
        conn.close()

    records.sort(key=lambda r: (str(r["buy_date"]), r["dm"]), reverse=True)
    return records


def save_records(combo: str, period: str, records: list[dict[str, Any]]) -> int:
    ensure_tables()
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "DELETE FROM history_replay WHERE combo = %s AND period = %s",
                (combo, period),
            )
            if records:
                cursor.executemany(
                    """
                    INSERT INTO history_replay
                      (combo, period, dm, mc, buy_date, entry, stop, exit_price, ret)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    [
                        (
                            r["combo"],
                            r["period"],
                            r["dm"],
                            r["mc"],
                            r["buy_date"],
                            r["entry"],
                            r["stop"],
                            r["exit_price"],
                            r["ret"],
                        )
                        for r in records
                    ],
                )
        conn.commit()
        return len(records)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def run(limit: int | None = None) -> list[dict[str, Any]]:
    ensure_tables()
    best = load_best_combo()
    if best is None or not best.get("combo"):
        print("[replay] combo_rank 为空，请先运行 run_miner.py")
        return []

    combo = str(best["combo"])
    period = str(best["period"])
    spec = _period_spec(period)
    hold_days = spec.hold_days if spec is not None else int(best.get("hold_days") or 0)
    stop_pct = spec.stop_pct if spec is not None else 0.08
    if hold_days <= 0:
        print(f"[replay] 未知周期 {period}")
        return []

    records = collect_records(combo, period, hold_days, stop_pct, limit=limit)
    n = save_records(combo, period, records)
    print(f"[replay] 完成，写入={n} 组合={combo} 周期={period}")
    if records:
        wins = [r for r in records if (to_float(r["ret"]) or 0.0) > 0]
        print(
            f"[replay] 测试期 {len(records)} 笔 盈利 {len(wins)} 笔 "
            f"胜率 {100.0 * len(wins) / len(records):.2f}%"
        )
        for r in records[:10]:
            print(
                f"[replay] {r['buy_date']} {r['dm']} {r['mc']} "
                f"买入={r['entry']} 止损={r['stop']} 收益={r['ret']:+.2f}%"
            )
    else:
        print("[replay] 测试期无回踩成交记录")
    return records


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="预计算最优组合历史回放并写入 history_replay")
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="仅回放前 N 只可交易股票（调试用）；默认全市场沪深非 ST",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.limit is not None and args.limit <= 0:
        print("[replay] --limit 必须为正整数")
        return 2
    run(args.limit)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
