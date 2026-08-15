"""动态选股：用 combo_rank 最优组合筛当日股票，剔除 ST 与京市。"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Optional

from src.combo.combination_miner import PERIODS, PeriodSpec
from src.combo.win_rate_ranker import ensure_tables as ensure_combo_tables
from src.db.connection import get_connection
from src.factor.factor_library import (
    combo_key,
    is_st_name,
    is_tradable_exchange,
    parse_combo,
)
from src.strategy.base_strategy import to_date, to_float

TOP_MIN = 5
TOP_MAX = 10
DEFAULT_TOP = 10


def _round2(value: float) -> float:
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _period_spec(period: str) -> Optional[PeriodSpec]:
    for spec in PERIODS:
        if spec.period == period:
            return spec
    return None


def latest_trade_date() -> Optional[date]:
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT MAX(t) AS t FROM factor_flag")
            row = cursor.fetchone()
            day = to_date(row["t"] if row else None)
            if day is not None:
                return day
            cursor.execute("SELECT MAX(t) AS t FROM daily_kline")
            row = cursor.fetchone()
            return to_date(row["t"] if row else None)
    finally:
        conn.close()


def load_best_combo() -> Optional[dict[str, Any]]:
    """综合训练+测试胜率最高的组合×周期。"""
    ensure_combo_tables()
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT combo, period, hold_days, train_win_rate, test_win_rate,
                       train_sample, test_sample, train_expectation, test_expectation
                FROM combo_rank
                ORDER BY (train_win_rate + test_win_rate) DESC,
                         test_win_rate DESC,
                         (train_sample + test_sample) DESC,
                         id ASC
                LIMIT 1
                """
            )
            row = cursor.fetchone()
            if not row:
                return None
            return {
                "combo": str(row["combo"] or "").strip(),
                "period": str(row["period"] or "").strip(),
                "hold_days": int(row["hold_days"] or 0),
                "train_win_rate": to_float(row["train_win_rate"]),
                "test_win_rate": to_float(row["test_win_rate"]),
                "train_sample": int(row["train_sample"] or 0),
                "test_sample": int(row["test_sample"] or 0),
                "train_expectation": to_float(row["train_expectation"]),
                "test_expectation": to_float(row["test_expectation"]),
            }
    finally:
        conn.close()


def _load_hits(day: date, factors: tuple[str, ...]) -> list[str]:
    if not factors:
        return []
    placeholders = ",".join(["%s"] * len(factors))
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT dm
                FROM factor_flag
                WHERE t = %s AND flag = 1 AND factor IN ({placeholders})
                GROUP BY dm
                HAVING COUNT(DISTINCT factor) = %s
                """,
                (day, *factors, len(factors)),
            )
            return [row["dm"] for row in cursor.fetchall()]
    finally:
        conn.close()


def _load_basics(dms: list[str]) -> dict[str, dict[str, Any]]:
    if not dms:
        return {}
    placeholders = ",".join(["%s"] * len(dms))
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT dm, mc, jys
                FROM stock_basic
                WHERE dm IN ({placeholders})
                """,
                tuple(dms),
            )
            return {row["dm"]: row for row in cursor.fetchall()}
    finally:
        conn.close()


def _load_klines_on(day: date, dms: list[str]) -> dict[str, dict[str, Any]]:
    if not dms:
        return {}
    placeholders = ",".join(["%s"] * len(dms))
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT dm, t, o, h, l, c, v
                FROM daily_kline
                WHERE t = %s AND dm IN ({placeholders})
                """,
                (day, *dms),
            )
            return {row["dm"]: row for row in cursor.fetchall()}
    finally:
        conn.close()


def _load_extra_factor_counts(day: date, dms: list[str]) -> dict[str, int]:
    if not dms:
        return {}
    placeholders = ",".join(["%s"] * len(dms))
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT dm, COUNT(*) AS n
                FROM factor_flag
                WHERE t = %s AND flag = 1 AND dm IN ({placeholders})
                GROUP BY dm
                """,
                (day, *dms),
            )
            return {row["dm"]: int(row["n"] or 0) for row in cursor.fetchall()}
    finally:
        conn.close()


def screen(
    trade_date: Optional[date] = None,
    top_n: int = DEFAULT_TOP,
) -> list[dict[str, Any]]:
    ensure_combo_tables()
    top_n = min(max(int(top_n), TOP_MIN), TOP_MAX)
    day = trade_date or latest_trade_date()
    if day is None:
        print("[screen] 无交易日数据，请先运行 run_factor.py")
        return []

    best = load_best_combo()
    if best is None or not best["combo"]:
        print("[screen] combo_rank 为空，请先运行 run_miner.py")
        return []

    factors = parse_combo(best["combo"])
    spec = _period_spec(best["period"])
    if spec is None:
        print(f"[screen] 未知周期 {best['period']}")
        return []

    print(
        f"[screen] 交易日={day} 最优组合={combo_key(factors)} "
        f"周期={spec.period}({spec.hold_days}日) 止损={spec.stop_pct * 100:.1f}% "
        f"训练胜率={best['train_win_rate']} 测试胜率={best['test_win_rate']} "
        f"样本={best['train_sample']}/{best['test_sample']}"
    )

    hit_dms = _load_hits(day, factors)
    basics = _load_basics(hit_dms)
    klines = _load_klines_on(day, hit_dms)
    extra_counts = _load_extra_factor_counts(day, hit_dms)

    candidates: list[dict[str, Any]] = []
    skipped_st = 0
    skipped_bj = 0
    for dm in hit_dms:
        basic = basics.get(dm) or {}
        if not is_tradable_exchange(basic.get("jys")):
            skipped_bj += 1
            continue
        if is_st_name(basic.get("mc")):
            skipped_st += 1
            continue
        bar = klines.get(dm) or {}
        close = to_float(bar.get("c"))
        volume = to_float(bar.get("v")) or 0.0
        if close is None or close <= 0:
            continue
        entry = _round2(close)
        stop = _round2(close * (1.0 - spec.stop_pct))
        candidates.append(
            {
                "t": day,
                "dm": dm,
                "mc": str(basic.get("mc") or ""),
                "combo": combo_key(factors),
                "period": spec.period,
                "hold_days": spec.hold_days,
                "entry_price": entry,
                "stop_loss": stop,
                "stop_pct": spec.stop_pct,
                "extra_hits": extra_counts.get(dm, 0),
                "volume": volume,
            }
        )

    candidates.sort(key=lambda r: (-r["extra_hits"], -r["volume"], r["dm"]))
    picked = candidates[:top_n]
    print(
        f"[screen] 命中={len(hit_dms)} 剔除ST={skipped_st} 剔除京市={skipped_bj} "
        f"可推荐={len(candidates)} 输出={len(picked)}"
    )
    for i, row in enumerate(picked, start=1):
        print(
            f"[screen] TOP{i} {row['dm']} {row['mc']} "
            f"命中组合={row['combo']} 周期={row['period']} "
            f"买入={row['entry_price']} 止损={row['stop_loss']}"
        )
    if not picked:
        print("[screen] 当日无满足最优组合的股票")
    return picked


def run(
    trade_date: Optional[date] = None,
    top_n: int = DEFAULT_TOP,
) -> list[dict[str, Any]]:
    return screen(trade_date=trade_date, top_n=top_n)
