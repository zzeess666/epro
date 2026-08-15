"""胜率排行：训练期 + 测试期双验证，写入 combo_rank。"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from src.combo.combination_miner import ComboPeriodStats, mine
from src.db.connection import get_connection

MIN_WIN_RATE = 60.0
MIN_SAMPLE = 25

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
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
"""


def ensure_tables() -> None:
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(_CREATE_COMBO_RANK)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _round2(value: float) -> float:
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def is_valid(row: ComboPeriodStats) -> bool:
    """训练、测试胜率均 ≥60%，且两期样本各 ≥ MIN_SAMPLE。"""
    return (
        row.train_n >= MIN_SAMPLE
        and row.test_n >= MIN_SAMPLE
        and row.train_win_rate >= MIN_WIN_RATE
        and row.test_win_rate >= MIN_WIN_RATE
    )


def rank_valid(rows: list[ComboPeriodStats]) -> list[ComboPeriodStats]:
    valid = [row for row in rows if is_valid(row)]
    valid.sort(
        key=lambda r: (
            -((r.train_win_rate + r.test_win_rate) / 2.0),
            -r.test_win_rate,
            -r.train_win_rate,
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
                       train_sample, test_sample)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
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


def run(limit: int | None = None) -> list[ComboPeriodStats]:
    """组合挖掘 + 双验证排行，只把达标组合写入 combo_rank。"""
    ensure_tables()
    print(
        f"[ranker] 有效门槛：训练/测试胜率≥{MIN_WIN_RATE:.0f}% "
        f"且样本各≥{MIN_SAMPLE}"
    )
    raw = mine(limit)
    valid = rank_valid(raw)
    save_ranks(valid)
    print(f"[ranker] 回测组合×周期={len(raw)} 双达标={len(valid)}")
    for i, row in enumerate(valid[:20], start=1):
        avg = (row.train_win_rate + row.test_win_rate) / 2.0
        print(
            f"[ranker] #{i} {row.combo} {row.period}({row.hold_days}日) "
            f"训练={_round2(row.train_win_rate)}% n={row.train_n} "
            f"测试={_round2(row.test_win_rate)}% n={row.test_n} "
            f"综合={_round2(avg)}%"
        )
    if not valid:
        print("[ranker] 无双达标组合（宁缺毋滥，未写入无效排行）")
    return valid
