#!/usr/bin/env python3
"""CLI：预计算达标组合满足日命中 + 7 周期收益，写入 bt_satisfy。

满足日 = 组合内全部因子当日均为 1；买入 = 满足日收盘，无回踩、无止损。
收益第 N 日 = 同股满足日之后第 N 条交易日收盘；未来 K 线不足则该周期跳过。
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from itertools import combinations
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from decimal import Decimal, ROUND_HALF_UP

from src.combo.combination_miner import _load_flags, load_tradable_codes
from src.combo.win_rate_ranker import ensure_tables as ensure_combo_tables
from src.db.connection import get_connection
from src.factor.factor_library import FACTOR_NAMES, combo_key, load_klines
from src.strategy.base_strategy import to_date

DAY_LEVELS: tuple[int, ...] = (1, 2, 3, 5, 7, 20, 60)
INSERT_CHUNK = 1000
_FACTOR_SET = set(FACTOR_NAMES)

_CREATE_BT_SATISFY = """
CREATE TABLE IF NOT EXISTS bt_satisfy (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  combo VARCHAR(200) NOT NULL COMMENT '组合，如 box_breakout+expma_golden+gap_up',
  dm VARCHAR(10) NOT NULL,
  mc VARCHAR(50),
  buy_date DATE NOT NULL COMMENT '满足日',
  start_price DECIMAL(10,2) COMMENT '满足日收盘',
  day_level INT NOT NULL COMMENT '1/2/3/5/7/20/60',
  end_date DATE COMMENT '目标日',
  end_price DECIMAL(10,2) COMMENT '目标日收盘',
  profit DECIMAL(10,2) COMMENT '收益%',
  UNIQUE KEY uq (combo, dm, buy_date, day_level),
  KEY idx_combo_level (combo, day_level, buy_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
"""


def ensure_tables() -> None:
    ensure_combo_tables()
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(_CREATE_BT_SATISFY)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _round2(value: float) -> float:
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _load_qualified_combos(cursor) -> set[str]:
    cursor.execute("SELECT DISTINCT combo FROM combo_rank WHERE combo IS NOT NULL AND combo <> ''")
    out: set[str] = set()
    for row in cursor.fetchall():
        key = str(row.get("combo") or "").strip()
        if key:
            out.add(key)
    return out


def _period_results(
    klines: list[dict[str, Any]],
    buy_index: int,
    start_price: float,
) -> list[tuple[int, Any, float, float]]:
    """满足日后第 N 个交易日收盘与收益；K 线不足则跳过该周期。"""
    if start_price <= 0:
        return []
    n = len(klines)
    rows: list[tuple[int, Any, float, float]] = []
    for day_level in DAY_LEVELS:
        end_index = buy_index + day_level
        if end_index >= n:
            continue
        end_close = klines[end_index].get("c")
        end_date = klines[end_index].get("t")
        if end_close is None or end_date is None:
            continue
        end_price = float(end_close)
        profit = (end_price - start_price) / start_price * 100.0
        rows.append((day_level, end_date, _round2(end_price), _round2(profit)))
    return rows


def _flush_rows(cursor, rows: list[tuple[Any, ...]]) -> int:
    if not rows:
        return 0
    placeholders = ",".join(["(%s,%s,%s,%s,%s,%s,%s,%s,%s)"] * len(rows))
    sql = (
        "REPLACE INTO bt_satisfy "
        "(combo, dm, mc, buy_date, start_price, day_level, end_date, end_price, profit) "
        "VALUES "
        + placeholders
    )
    flat: list[Any] = []
    for item in rows:
        flat.extend(item)
    cursor.execute(sql, flat)
    return len(rows)


def build(limit: int | None = None, days: int = 180) -> int:
    """遍历全市场 factor_flag，写入达标组合满足记录。返回写入行数。

    days：只保留最近 N 自然日的满足日（避免全历史数据爆炸）。
    """
    ensure_tables()
    codes = load_tradable_codes(limit)
    conn = get_connection()
    written = 0
    try:
        with conn.cursor() as cursor:
            qualified = _load_qualified_combos(cursor)
            if not qualified:
                print("[bt] combo_rank 为空，请先运行 run_miner.py")
                return 0
            cursor.execute("SELECT MAX(t) AS latest FROM daily_kline")
            _latest = cursor.fetchone().get("latest")
            if _latest is None:
                print("[bt] daily_kline 为空")
                return 0
            cutoff = to_date(_latest) - timedelta(days=days)
            cursor.execute("SELECT dm, mc FROM stock_basic")
            name_map = {row["dm"]: str(row.get("mc") or "") for row in cursor.fetchall()}
            print(
                f"[bt] 达标组合={len(qualified)} 股票={len(codes)} "
                f"周期={list(DAY_LEVELS)} 买入=满足日收盘 无回踩无止损 "
                f"仅保留最近{days}天(buy_date>={cutoff})"
            )
            if not codes:
                print("[bt] 无可用股票（需沪深非 ST）")
                return 0
            cursor.execute("DELETE FROM bt_satisfy")
            conn.commit()

            pending: list[tuple[Any, ...]] = []
            last_commit = 0
            for index, dm in enumerate(codes, start=1):
                flags_by_date = _load_flags(cursor, dm)
                if not flags_by_date:
                    if index % 50 == 0 or index == len(codes):
                        print(f"[bt] 进度 {index}/{len(codes)} 写入={written}")
                    continue
                klines = load_klines(dm, cursor)
                date_to_index = {
                    bar["t"]: i for i, bar in enumerate(klines) if bar["t"] is not None
                }
                mc = name_map.get(dm, "")
                for day, hit_factors in flags_by_date.items():
                    if day < cutoff:
                        continue
                    known = [name for name in sorted(hit_factors) if name in _FACTOR_SET]
                    if len(known) < 2:
                        continue
                    buy_index = date_to_index.get(day)
                    if buy_index is None:
                        continue
                    close = klines[buy_index].get("c")
                    if close is None or float(close) <= 0:
                        continue
                    matched: list[str] = []
                    if len(known) >= 2:
                        for combo in combinations(known, 2):
                            key = combo_key(combo)
                            if key in qualified:
                                matched.append(key)
                    if len(known) >= 3:
                        for combo in combinations(known, 3):
                            key = combo_key(combo)
                            if key in qualified:
                                matched.append(key)
                    if not matched:
                        continue
                    start_price = _round2(float(close))
                    periods = _period_results(klines, buy_index, start_price)
                    if not periods:
                        continue
                    for key in matched:
                        for day_level, end_date, end_price, profit in periods:
                            pending.append(
                                (
                                    key,
                                    dm,
                                    mc,
                                    day,
                                    start_price,
                                    day_level,
                                    end_date,
                                    end_price,
                                    profit,
                                )
                            )
                            if len(pending) >= INSERT_CHUNK:
                                written += _flush_rows(cursor, pending)
                                pending.clear()
                                if written - last_commit >= INSERT_CHUNK * 10:
                                    conn.commit()
                                    last_commit = written
                if index % 50 == 0 or index == len(codes):
                    print(f"[bt] 进度 {index}/{len(codes)} 写入={written + len(pending)}")
            written += _flush_rows(cursor, pending)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    print(f"[bt] 完成，写入={written}")
    return written


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="预计算达标组合满足日收益并写入 bt_satisfy")
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="仅计算前 N 只可交易股票（调试用）；默认全市场沪深非 ST",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.limit is not None and args.limit <= 0:
        print("[bt] --limit 必须为正整数")
        return 2
    build(args.limit)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
