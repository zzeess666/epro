"""盈亏比排行：训练期 + 测试期双验证，写入 combo_rank。"""

from __future__ import annotations

import math
from decimal import Decimal, ROUND_HALF_UP

from src.combo.combination_miner import ComboPeriodStats, mine
from src.db.connection import get_connection

MIN_SAMPLE = 25
MIN_PROFIT_RATIO = 1.2

_CREATE_COMBO_RANK = """
CREATE TABLE IF NOT EXISTS combo_rank (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  combo VARCHAR(200) COMMENT '指标组合，如 macd_golden+gap_up',
  period VARCHAR(10) COMMENT '周期标签 超短/短/中短/中',
  hold_days INT,
  train_win_rate DECIMAL(5,2),
  test_win_rate DECIMAL(5,2),
  train_sample INT,
  test_sample INT,
  train_avg_win DECIMAL(10,2),
  train_avg_loss DECIMAL(10,2),
  test_avg_win DECIMAL(10,2),
  test_avg_loss DECIMAL(10,2),
  train_ratio DECIMAL(10,2),
  test_ratio DECIMAL(10,2),
  train_expectation DECIMAL(10,4),
  test_expectation DECIMAL(10,4),
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
"""

_COMBO_RANK_EXTRA_COLUMNS: tuple[tuple[str, str], ...] = (
    ("train_avg_win", "DECIMAL(10,2)"),
    ("train_avg_loss", "DECIMAL(10,2)"),
    ("test_avg_win", "DECIMAL(10,2)"),
    ("test_avg_loss", "DECIMAL(10,2)"),
    ("train_ratio", "DECIMAL(10,2)"),
    ("test_ratio", "DECIMAL(10,2)"),
    ("train_expectation", "DECIMAL(10,4)"),
    ("test_expectation", "DECIMAL(10,4)"),
)

_RATIO_MAX = 99999999.99


def ensure_tables() -> None:
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(_CREATE_COMBO_RANK)
            cursor.execute("SHOW COLUMNS FROM combo_rank")
            existing = set()
            for row in cursor.fetchall():
                field = row.get("Field", row.get("field", ""))
                if field:
                    existing.add(str(field))
            for name, ddl in _COMBO_RANK_EXTRA_COLUMNS:
                if name not in existing:
                    cursor.execute(f"ALTER TABLE combo_rank ADD COLUMN {name} {ddl}")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _quantize(value: float, places: str) -> float:
    if not math.isfinite(value):
        if math.isinf(value) and value > 0:
            return float(Decimal(str(_RATIO_MAX)).quantize(Decimal(places), rounding=ROUND_HALF_UP))
        return 0.0
    return float(Decimal(str(value)).quantize(Decimal(places), rounding=ROUND_HALF_UP))


def _round2(value: float) -> float:
    return _quantize(value, "0.01")


def _round4(value: float) -> float:
    return _quantize(value, "0.0001")


def is_valid(row: ComboPeriodStats) -> bool:
    """训练、测试各满足 n≥25 且期望收益>0 且盈亏比≥1.2。"""
    return (
        row.train_n >= MIN_SAMPLE
        and row.test_n >= MIN_SAMPLE
        and row.train_expectation > 0
        and row.test_expectation > 0
        and row.train_ratio >= MIN_PROFIT_RATIO
        and row.test_ratio >= MIN_PROFIT_RATIO
    )


def rank_valid(rows: list[ComboPeriodStats]) -> list[ComboPeriodStats]:
    valid = [row for row in rows if is_valid(row)]
    valid.sort(
        key=lambda r: (
            -(r.test_expectation + r.train_expectation),
            -r.test_expectation,
            -r.train_expectation,
            -(r.train_n + r.test_n),
            r.combo,
            r.period,
        )
    )
    return valid


def save_ranks(rows: list[ComboPeriodStats]) -> int:
    ensure_tables()
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("DELETE FROM combo_rank")
            if rows:
                cursor.executemany(
                    """
                    INSERT INTO combo_rank
                      (combo, period, hold_days, train_win_rate, test_win_rate,
                       train_sample, test_sample,
                       train_avg_win, train_avg_loss, test_avg_win, test_avg_loss,
                       train_ratio, test_ratio, train_expectation, test_expectation)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    [
                        (
                            r.combo,
                            r.period,
                            r.hold_days,
                            _round2(r.train_win_rate),
                            _round2(r.test_win_rate),
                            r.train_n,
                            r.test_n,
                            _round2(r.train_avg_win),
                            _round2(r.train_avg_loss),
                            _round2(r.test_avg_win),
                            _round2(r.test_avg_loss),
                            _round2(r.train_ratio),
                            _round2(r.test_ratio),
                            _round4(r.train_expectation),
                            _round4(r.test_expectation),
                        )
                        for r in rows
                    ],
                )
        conn.commit()
        return len(rows)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _fmt_ratio(value: float) -> str:
    if math.isinf(value) and value > 0:
        return "inf"
    return f"{_round2(value)}"


def run(limit: int | None = None) -> list[ComboPeriodStats]:
    """组合挖掘 + 双验证排行，只把达标组合写入 combo_rank。"""
    ensure_tables()
    print(
        f"[ranker] 有效门槛：训练/测试 n≥{MIN_SAMPLE} "
        f"且期望收益>0 且盈亏比≥{MIN_PROFIT_RATIO}"
    )
    raw = mine(limit)
    valid = rank_valid(raw)
    save_ranks(valid)
    print(f"[ranker] 回测组合×周期={len(raw)} 双达标={len(valid)}")
    for i, row in enumerate(valid[:20], start=1):
        print(
            f"[ranker] #{i} {row.combo} {row.period}({row.hold_days}日) "
            f"训练={_round2(row.train_win_rate)}% n={row.train_n} "
            f"均盈={_round2(row.train_avg_win)} 均亏={_round2(row.train_avg_loss)} "
            f"盈亏比={_fmt_ratio(row.train_ratio)} 期望={_round4(row.train_expectation)} "
            f"测试={_round2(row.test_win_rate)}% n={row.test_n} "
            f"均盈={_round2(row.test_avg_win)} 均亏={_round2(row.test_avg_loss)} "
            f"盈亏比={_fmt_ratio(row.test_ratio)} 期望={_round4(row.test_expectation)}"
        )
    if not valid:
        print("[ranker] 无双达标组合（宁缺毋滥，未写入无效排行）")
    return valid
