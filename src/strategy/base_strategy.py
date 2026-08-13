"""策略基类：统一 signal 输出接口，以及本地 K 线读取（≤100 只）。"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Optional

from config.config import SYNC_STOCK_LIMIT
from src.db.connection import get_connection

STRATEGY_CODES = ("A", "B", "C")

_CREATE_STRATEGY_SIGNAL = """
CREATE TABLE IF NOT EXISTS strategy_signal (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  dm VARCHAR(10) NOT NULL,
  t DATE NOT NULL,
  strategy VARCHAR(10) NOT NULL COMMENT 'A/B/C',
  score DECIMAL(10,2),
  entry_price DECIMAL(10,2),
  stop_loss DECIMAL(10,2),
  detail TEXT COMMENT 'JSON 信号详情',
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  KEY idx_dm_t (dm, t)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
"""

_CREATE_BACKTEST_RESULT = """
CREATE TABLE IF NOT EXISTS backtest_result (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  strategy VARCHAR(10) NOT NULL,
  start_date DATE,
  end_date DATE,
  hold_days INT,
  sample_count INT,
  win_count INT,
  win_rate DECIMAL(5,2),
  avg_return DECIMAL(10,2),
  avg_loss DECIMAL(10,2),
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
"""


def ensure_tables() -> None:
    """幂等建表，与 sql/schema.sql 中 M2 两张表一致。"""
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(_CREATE_STRATEGY_SIGNAL)
            cursor.execute(_CREATE_BACKTEST_RESULT)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@dataclass
class Signal:
    dm: str
    t: date
    strategy: str
    entry_price: float
    stop_loss: float
    score: Optional[float] = None
    detail: Optional[dict[str, Any]] = None

    def to_row(self) -> tuple:
        return (
            self.dm,
            self.t,
            self.strategy,
            None if self.score is None else _round2(self.score),
            _round2(self.entry_price),
            _round2(self.stop_loss),
            None if self.detail is None else json.dumps(self.detail, ensure_ascii=False, default=str),
        )


def _round2(value: float) -> float:
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def to_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def to_date(value: Any) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()[:10]
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def normalize_kline(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "t": to_date(row.get("t")),
        "o": to_float(row.get("o")),
        "h": to_float(row.get("h")),
        "l": to_float(row.get("l")),
        "c": to_float(row.get("c")),
        "v": to_float(row.get("v")),
        "a": to_float(row.get("a")),
        "pc": to_float(row.get("pc")),
        "ma5": to_float(row.get("ma5")),
        "ma10": to_float(row.get("ma10")),
        "ma20": to_float(row.get("ma20")),
        "ma60": to_float(row.get("ma60")),
    }


def load_stock_codes(limit: int | None = None) -> list[str]:
    cap = SYNC_STOCK_LIMIT if limit is None else min(int(limit), SYNC_STOCK_LIMIT)
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
                (cap,),
            )
            return [row["dm"] for row in cursor.fetchall()]
    finally:
        conn.close()


def load_klines(dm: str) -> list[dict[str, Any]]:
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT t, o, h, l, c, v, a, pc, ma5, ma10, ma20, ma60
                FROM daily_kline
                WHERE dm = %s
                ORDER BY t ASC
                """,
                (dm,),
            )
            return [normalize_kline(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def avg_volume(klines: list[dict[str, Any]], start: int, end: int) -> Optional[float]:
    """区间 [start, end) 成交量均值。"""
    if start < 0 or end > len(klines) or end <= start:
        return None
    vols: list[float] = []
    for i in range(start, end):
        vol = klines[i]["v"]
        if vol is None:
            return None
        vols.append(vol)
    if not vols:
        return None
    return sum(vols) / len(vols)


def breakout_strength(klines: list[dict[str, Any]], index: int) -> int:
    """从某日往前数，收盘价连续高于更早 K 线最高价的天数（遇不满足即停止）。"""
    close = klines[index]["c"]
    if close is None:
        return 0
    strength = 0
    for j in range(index - 1, -1, -1):
        high = klines[j]["h"]
        if high is None or close <= high:
            break
        strength += 1
    return strength


class BaseStrategy(ABC):
    name: str = ""
    min_bars: int = 1

    @abstractmethod
    def evaluate(self, dm: str, klines: list[dict[str, Any]], index: int) -> Optional[Signal]:
        """判断 index 日是否触发信号。klines 按日期升序。"""

    def scan(self, dm: str, klines: list[dict[str, Any]]) -> list[Signal]:
        signals: list[Signal] = []
        if len(klines) < self.min_bars:
            return signals
        start = max(self.min_bars - 1, 0)
        for index in range(start, len(klines)):
            signal = self.evaluate(dm, klines, index)
            if signal is None:
                continue
            if signal.t is None:
                continue
            if signal.stop_loss is None or signal.entry_price is None:
                continue
            if signal.entry_price <= 0 or signal.stop_loss <= 0:
                continue
            signals.append(signal)
        return signals


def replace_signals(strategy: str, signals: list[Signal]) -> int:
    """按策略覆盖写入 strategy_signal，保证重复跑不堆重复行。"""
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("DELETE FROM strategy_signal WHERE strategy = %s", (strategy,))
            if signals:
                cursor.executemany(
                    """
                    INSERT INTO strategy_signal
                      (dm, t, strategy, score, entry_price, stop_loss, detail)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    [s.to_row() for s in signals],
                )
        conn.commit()
        return len(signals)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def run(strategy_code: str | None = None, limit: int | None = None) -> dict[str, int]:
    """扫描 ≤100 只股票历史 K 线，生成并写入策略信号。"""
    from src.strategy import iter_strategies

    ensure_tables()
    codes = load_stock_codes(limit)
    strategies = iter_strategies(strategy_code)
    counts: dict[str, int] = {s.name: 0 for s in strategies}

    if not codes:
        print("[strategy] stock_basic 为空，请先完成 M1 同步")
        for s in strategies:
            replace_signals(s.name, [])
        return counts

    print(f"[strategy] 开始扫描 股票={len(codes)} 策略={[s.name for s in strategies]}")
    collected: dict[str, list[Signal]] = {s.name: [] for s in strategies}

    for i, dm in enumerate(codes, start=1):
        klines = load_klines(dm)
        for strategy in strategies:
            collected[strategy.name].extend(strategy.scan(dm, klines))
        if i % 10 == 0 or i == len(codes):
            print(f"[strategy] 进度 {i}/{len(codes)}")

    for strategy in strategies:
        n = replace_signals(strategy.name, collected[strategy.name])
        counts[strategy.name] = n
        print(f"[strategy] {strategy.name} 信号数={n}")

    return counts
