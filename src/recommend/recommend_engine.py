"""推荐引擎：读当日信号 → 风控过滤 → 统一评分 → TOP3 入库。"""

from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Optional

from src.db.connection import get_connection
from src.risk.risk_filter import filter_signals
from src.strategy.base_strategy import ensure_tables as ensure_strategy_tables

TOP_N = 3
DEFAULT_POSITION_PCT = 10.0
BASE_SCORE_A = 70.0
BASE_SCORE_B = 65.0

_CREATE_RECOMMEND_RESULT = """
CREATE TABLE IF NOT EXISTS recommend_result (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  t DATE NOT NULL COMMENT '推荐日期',
  dm VARCHAR(10) NOT NULL,
  strategy VARCHAR(10) COMMENT '命中策略',
  score DECIMAL(10,2) COMMENT '综合评分',
  reason TEXT COMMENT '推荐理由',
  entry_price DECIMAL(10,2),
  stop_loss DECIMAL(10,2),
  position_pct DECIMAL(5,2) COMMENT '建议仓位',
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  KEY idx_t (t)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
"""


def ensure_tables() -> None:
    ensure_strategy_tables()
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(_CREATE_RECOMMEND_RESULT)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def run(trade_date: Optional[date] = None) -> list[dict[str, Any]]:
    """生成指定交易日（默认最新）的 TOP3 推荐。"""
    ensure_tables()
    day = trade_date or _latest_trade_date()
    if day is None:
        print("[recommend] 无交易日数据，请先完成 M1/M2")
        return []

    signals = _load_signals(day)
    print(f"[recommend] 交易日={day} 原始信号={len(signals)}")
    passed, _stats = filter_signals(signals)
    ranked = _rank_top(passed, TOP_N)
    _replace_results(day, ranked)
    for i, row in enumerate(ranked, start=1):
        print(
            f"[recommend] TOP{i} {row['dm']} 策略={row['strategy']} "
            f"评分={row['score']} 买入={row['entry_price']} "
            f"止损={row['stop_loss']} 仓位={row['position_pct']}%"
        )
        print(f"            {row['reason']}")
    if not ranked:
        print("[recommend] 风控后无推荐（宁缺毋滥）")
    else:
        print(f"[recommend] 写入 recommend_result {len(ranked)} 条")
    return ranked


def _latest_trade_date() -> Optional[date]:
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT MAX(t) AS t FROM daily_kline")
            row = cursor.fetchone()
            day = _to_date(row["t"] if row else None)
            if day is not None:
                return day
            cursor.execute("SELECT MAX(t) AS t FROM strategy_signal")
            row = cursor.fetchone()
            return _to_date(row["t"] if row else None)
    finally:
        conn.close()


def _load_signals(day: date) -> list[dict[str, Any]]:
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT s.dm, s.t, s.strategy, s.score, s.entry_price, s.stop_loss, s.detail,
                       b.mc, b.ltsz, b.pe, b.pb
                FROM strategy_signal s
                LEFT JOIN stock_basic b ON b.dm = s.dm
                WHERE s.t = %s
                ORDER BY s.strategy, s.dm
                """,
                (day,),
            )
            rows = cursor.fetchall()
    finally:
        conn.close()
    out: list[dict[str, Any]] = []
    for row in rows:
        out.append(
            {
                "dm": row["dm"],
                "t": _to_date(row["t"]),
                "strategy": str(row["strategy"] or "").strip().upper(),
                "score": _to_float(row["score"]),
                "entry_price": _to_float(row["entry_price"]),
                "stop_loss": _to_float(row["stop_loss"]),
                "detail": row.get("detail"),
                "mc": row.get("mc"),
                "ltsz": _to_float(row.get("ltsz")),
                "pe": _to_float(row.get("pe")),
                "pb": _to_float(row.get("pb")),
            }
        )
    return out


def _rank_top(signals: list[dict[str, Any]], n: int) -> list[dict[str, Any]]:
    scored: list[dict[str, Any]] = []
    for sig in signals:
        score = _unified_score(sig)
        if score is None:
            continue
        entry = sig.get("entry_price")
        stop = sig.get("stop_loss")
        if entry is None or stop is None:
            continue
        row = {
            "t": sig["t"],
            "dm": sig["dm"],
            "strategy": sig["strategy"],
            "score": _round2(score),
            "reason": _reason(sig["strategy"], score, stop),
            "entry_price": _round2(float(entry)),
            "stop_loss": _round2(float(stop)),
            "position_pct": _round2(DEFAULT_POSITION_PCT),
        }
        scored.append(row)

    scored.sort(key=lambda r: (-r["score"], r["dm"]))
    picked: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in scored:
        if row["dm"] in seen:
            continue
        seen.add(row["dm"])
        picked.append(row)
        if len(picked) >= n:
            break
    return picked


def _unified_score(sig: dict[str, Any]) -> Optional[float]:
    strategy = sig.get("strategy")
    detail = _parse_detail(sig.get("detail"))
    if strategy == "C":
        score = sig.get("score")
        return None if score is None else float(score)
    if strategy == "A":
        score = BASE_SCORE_A
        strength = detail.get("today_strength")
        if isinstance(strength, (int, float)) and strength >= 40:
            score += 3
        days = detail.get("pullback_days")
        if isinstance(days, (int, float)) and 1 <= days <= 3:
            score += 2
        return score
    if strategy == "B":
        score = BASE_SCORE_B
        vol = detail.get("vol_vs_5d")
        if isinstance(vol, (int, float)) and vol <= 0.35:
            score += 3
        if detail.get("near") == "ma10":
            score += 2
        return score
    return None


def _reason(strategy: str, score: float, stop_loss: float) -> str:
    s = _round2(score)
    y = _round2(float(stop_loss))
    if strategy == "A":
        return f"二次突破形态，评分 {s} 分，止损 {y} 元"
    if strategy == "B":
        return f"缩量回踩支撑，评分 {s} 分，止损 {y} 元"
    if strategy == "C":
        return f"综合评分 {s} 分，技术形态与资金活跃度达标"
    return f"策略{strategy}，评分 {s} 分，止损 {y} 元"


def _replace_results(day: date, rows: list[dict[str, Any]]) -> None:
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("DELETE FROM recommend_result WHERE t = %s", (day,))
            if rows:
                cursor.executemany(
                    """
                    INSERT INTO recommend_result
                      (t, dm, strategy, score, reason, entry_price, stop_loss, position_pct)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    [
                        (
                            r["t"],
                            r["dm"],
                            r["strategy"],
                            r["score"],
                            r["reason"],
                            r["entry_price"],
                            r["stop_loss"],
                            r["position_pct"],
                        )
                        for r in rows
                    ],
                )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _parse_detail(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _to_date(value: Any) -> Optional[date]:
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


def _to_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _round2(value: float) -> float:
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
