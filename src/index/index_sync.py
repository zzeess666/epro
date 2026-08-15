"""同步大盘指数日K，本地计算 MA20 写入 index_kline。"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Optional

from src.api.mairui_client import MairuiClient
from src.db.connection import get_connection

# 上证 / 深成 / 科创50 / 创业板
INDEX_CODES: tuple[str, ...] = (
    "000001.SH",
    "399001.SZ",
    "000688.SH",
    "399006.SZ",
)

INIT_START = date(2015, 1, 1)
MA20_WINDOW = 20

_CREATE_INDEX_KLINE = """
CREATE TABLE IF NOT EXISTS index_kline (
  code VARCHAR(20) NOT NULL COMMENT '指数代码，如000001.SH',
  t DATE NOT NULL,
  o DECIMAL(10,2), h DECIMAL(10,2), l DECIMAL(10,2), c DECIMAL(10,2),
  v BIGINT, a DECIMAL(20,2), pc DECIMAL(10,2),
  ma20 DECIMAL(10,2),
  PRIMARY KEY (code, t)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
"""


def ensure_tables() -> None:
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(_CREATE_INDEX_KLINE)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _round2(value: float) -> float:
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _to_date_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip().replace("/", "-")
    if not text:
        return None
    compact = text.replace("-", "")
    if len(compact) >= 8 and compact[:8].isdigit():
        return f"{compact[:4]}-{compact[4:6]}-{compact[6:8]}"
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


def _calc_ma20(closes: list[Optional[float]]) -> list[Optional[float]]:
    """按日期升序收盘价计算 MA20；仅用当日及之前数据，样本不足为 None。"""
    out: list[Optional[float]] = [None] * len(closes)
    running: list[float] = []
    for i, close in enumerate(closes):
        if close is None:
            continue
        running.append(float(close))
        if len(running) >= MA20_WINDOW:
            window = running[-MA20_WINDOW:]
            out[i] = _round2(sum(window) / MA20_WINDOW)
    return out


def _normalize_rows(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """解析接口行并按交易日升序去重。"""
    by_day: dict[str, dict[str, Any]] = {}
    for row in raw:
        trade_date = _to_date_str(row.get("t"))
        if not trade_date:
            continue
        by_day[trade_date] = {
            "t": trade_date,
            "o": _to_decimal(row.get("o")),
            "h": _to_decimal(row.get("h")),
            "l": _to_decimal(row.get("l")),
            "c": _to_decimal(row.get("c")),
            "v": _to_int(row.get("v")),
            "a": _to_decimal(row.get("a")),
            "pc": _to_decimal(row.get("pc")),
        }
    ordered = [by_day[k] for k in sorted(by_day.keys())]
    ma20s = _calc_ma20([r["c"] for r in ordered])
    for i, row in enumerate(ordered):
        row["ma20"] = ma20s[i]
    return ordered


def _upsert_index_klines(code: str, rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 0
    payload = [
        (
            code,
            row["t"],
            row["o"],
            row["h"],
            row["l"],
            row["c"],
            row["v"],
            row["a"],
            row["pc"],
            row["ma20"],
        )
        for row in rows
    ]
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.executemany(
                """
                REPLACE INTO index_kline (code, t, o, h, l, c, v, a, pc, ma20)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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


def sync_one(
    code: str,
    start: date | None = None,
    end: date | None = None,
    client: MairuiClient | None = None,
) -> int:
    """同步单只指数日K并写入 MA20，返回入库条数。"""
    ensure_tables()
    symbol = str(code).strip().upper()
    start_day = start or INIT_START
    end_day = end or date.today()
    api = client or MairuiClient()
    raw = api.get_index_history(
        code=symbol,
        start=start_day.strftime("%Y%m%d"),
        end=end_day.strftime("%Y%m%d"),
    )
    rows = _normalize_rows(raw)
    written = _upsert_index_klines(symbol, rows)
    print(f"[index] {symbol} 入库 {written} 条（含 ma20）")
    return written


def run(
    codes: tuple[str, ...] | list[str] | None = None,
    start: date | None = None,
    end: date | None = None,
) -> int:
    """同步指定指数（默认4只）2015-01-01 至今。"""
    ensure_tables()
    targets = tuple(codes) if codes is not None else INDEX_CODES
    start_day = start or INIT_START
    end_day = end or date.today()
    client = MairuiClient()
    total = 0
    failed = 0
    print(
        f"[index] 开始同步 {len(targets)} 只指数 "
        f"{start_day.isoformat()} ~ {end_day.isoformat()}"
    )
    for symbol in targets:
        try:
            total += sync_one(symbol, start=start_day, end=end_day, client=client)
        except Exception as exc:
            failed += 1
            print(f"[index] {symbol} 失败: {exc}")
    print(f"[index] 完成，累计入库 {total} 条，失败 {failed} 只")
    return total


if __name__ == "__main__":
    run()
