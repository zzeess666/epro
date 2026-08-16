"""FastAPI：推荐列表 / 跟踪状态 / 历史回放 / 组合排行 / 手动回溯 / 首页。"""

from __future__ import annotations

import base64
import math
import os
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from fastapi import FastAPI, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from src.combo.combination_miner import (
    PERIODS,
    ComboPeriodStats,
    _find_pullback_entry,
    is_market_bull,
    load_index_bull_map,
    load_tradable_codes,
    load_trade_dates,
    split_train_test,
)
from src.combo.win_rate_ranker import ensure_tables as ensure_combo_tables
from src.db.connection import get_connection
from src.factor.factor_library import FACTOR_NAMES, combo_key, load_klines
from src.screen.dynamic_screener import load_best_combo
from src.strategy.base_strategy import to_date, to_float
from src.track.track_service import list_watches, load_latest_recommend, now_cn

PUBLIC_DIR = ROOT / "public"
INDEX_HTML = PUBLIC_DIR / "index.html"

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

KLINE_WINDOW_DAYS = 30
BACKTEST_RECORD_DEFAULT = 100
BACKTEST_RECORD_MAX = 500
_FACTOR_SET = set(FACTOR_NAMES)
_PERIOD_MAP = {spec.period: spec for spec in PERIODS}

app = FastAPI(title="EPro", docs_url=None, redoc_url=None)


class _BasicAuthMiddleware(BaseHTTPMiddleware):
    """HTTP Basic 认证，保护整站。"""

    def __init__(self, app, username: str, password: str) -> None:
        super().__init__(app)
        self._username = username
        self._password = password

    async def dispatch(self, request: Request, call_next):
        auth = request.headers.get("Authorization", "")
        if not self._check(auth):
            return Response(
                "Unauthorized",
                status_code=401,
                headers={"WWW-Authenticate": 'Basic realm="EPro"'},
            )
        return await call_next(request)

    def _check(self, auth: str) -> bool:
        if not auth.startswith("Basic "):
            return False
        try:
            decoded = base64.b64decode(auth[6:]).decode("utf-8")
            username, password = decoded.split(":", 1)
            return username == self._username and password == self._password
        except Exception:
            return False


_WEB_USER = os.getenv("WEB_USER", "admin")
_WEB_PASSWORD = os.getenv("WEB_PASSWORD", "epro2026")
app.add_middleware(_BasicAuthMiddleware, username=_WEB_USER, password=_WEB_PASSWORD)


def _ensure_history_replay() -> None:
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


def _num(value: Any) -> float | int | None:
    if value is None:
        return None
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    num = to_float(value)
    return num


def _load_klines_window(cursor, dm: str, buy_date: date) -> list[dict[str, Any]]:
    start = buy_date - timedelta(days=KLINE_WINDOW_DAYS)
    end = buy_date + timedelta(days=KLINE_WINDOW_DAYS)
    cursor.execute(
        """
        SELECT t, o, h, l, c, v, ma5, ma10, ma20
        FROM daily_kline
        WHERE dm = %s AND t BETWEEN %s AND %s
        ORDER BY t
        """,
        (dm, start, end),
    )
    rows: list[dict[str, Any]] = []
    for row in cursor.fetchall():
        day = to_date(row.get("t"))
        rows.append(
            {
                "t": day.isoformat() if day else None,
                "o": _num(row.get("o")),
                "h": _num(row.get("h")),
                "l": _num(row.get("l")),
                "c": _num(row.get("c")),
                "v": _num(row.get("v")),
                "ma5": _num(row.get("ma5")),
                "ma10": _num(row.get("ma10")),
                "ma20": _num(row.get("ma20")),
            }
        )
    return rows


def _round2(value: float) -> float:
    if not math.isfinite(value):
        return 0.0
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _round_ratio(value: float) -> float:
    if math.isinf(value) and value > 0:
        return 99999999.99
    if not math.isfinite(value):
        return 0.0
    return _round2(value)


def _parse_factors(raw: str) -> tuple[str, ...] | None:
    parts: list[str] = []
    seen: set[str] = set()
    for item in str(raw or "").split(","):
        name = item.strip()
        if not name or name in seen:
            continue
        if name not in _FACTOR_SET:
            return None
        seen.add(name)
        parts.append(name)
    if len(parts) < 2 or len(parts) > 3:
        return None
    return tuple(parts)


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


def _backtest_one_combo(factors: tuple[str, ...], period: str) -> tuple[ComboPeriodStats, list[dict[str, Any]]]:
    """只回测指定 2-3 因子组合：回踩买入 + 大盘过滤 + 止损 8%；仅测试期。"""
    spec = _PERIOD_MAP[period]
    key = combo_key(factors)
    stats = ComboPeriodStats(
        combo=key,
        period=spec.period,
        hold_days=spec.hold_days,
        stop_pct=spec.stop_pct,
    )
    dates = load_trade_dates()
    _, test_dates = split_train_test(dates)
    codes = load_tradable_codes()
    bull_map = load_index_bull_map()
    factor_list = list(factors)
    target = set(factors)
    placeholders = ",".join(["%s"] * len(factor_list))
    records: list[dict[str, Any]] = []
    if not codes or not test_dates:
        return stats, records

    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT dm, mc FROM stock_basic")
            name_map = {row["dm"]: str(row.get("mc") or "") for row in cursor.fetchall()}
            for dm in codes:
                cursor.execute(
                    f"""
                    SELECT t, factor
                    FROM factor_flag
                    WHERE dm = %s AND flag = 1 AND factor IN ({placeholders})
                    """,
                    (dm, *factor_list),
                )
                flags_by_date: dict[date, set[str]] = defaultdict(set)
                for row in cursor.fetchall():
                    day = to_date(row["t"])
                    factor = str(row["factor"] or "").strip()
                    if day is None or not factor:
                        continue
                    flags_by_date[day].add(factor)
                if not flags_by_date:
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
                        klines, entry_index, entry_price, spec.hold_days, spec.stop_pct
                    )
                    if sim is None:
                        continue
                    exit_price, ret = sim
                    stats.add(ret, is_train=False)
                    buy_date = klines[entry_index]["t"]
                    records.append(
                        {
                            "dm": dm,
                            "mc": name_map.get(dm, ""),
                            "buy_date": buy_date,
                            "entry": _round2(entry_price),
                            "stop": _round2(entry_price * (1.0 - spec.stop_pct)),
                            "exit_price": _round2(exit_price),
                            "ret": _round2(ret),
                        }
                    )
    finally:
        conn.close()

    records.sort(key=lambda r: (str(r["buy_date"]), r["dm"]), reverse=True)
    return stats, records


def _serialize_backtest_record(row: dict[str, Any]) -> dict[str, Any]:
    buy_date = to_date(row.get("buy_date"))
    return {
        "dm": str(row.get("dm") or "").strip(),
        "mc": str(row.get("mc") or ""),
        "buy_date": buy_date.isoformat() if buy_date else None,
        "entry": _num(row.get("entry")),
        "stop": _num(row.get("stop")),
        "exit_price": _num(row.get("exit_price")),
        "ret": _num(row.get("ret")),
    }


@app.get("/api/recommend")
def api_recommend() -> JSONResponse:
    rows, day = load_latest_recommend()
    return JSONResponse(
        {
            "date": _date_str(day),
            "items": [_jsonable(r) for r in rows],
        }
    )


@app.get("/api/track")
def api_track() -> JSONResponse:
    rows = list_watches()
    day = rows[0]["track_date"] if rows else now_cn().date()
    alerts = [
        {
            "dm": r.get("dm"),
            "mc": r.get("mc"),
            "current_price": r.get("current_price"),
            "entry_price": r.get("entry_price"),
            "stop_loss": r.get("stop_loss"),
        }
        for r in rows
        if r.get("status") == "达标"
    ]
    return JSONResponse(
        {
            "date": _date_str(day),
            "items": [_jsonable(r) for r in rows],
            "alerts": alerts,
        }
    )


@app.get("/api/history")
def api_history() -> JSONResponse:
    _ensure_history_replay()
    best = load_best_combo() or {}
    combo = str(best.get("combo") or "").strip()
    period = str(best.get("period") or "").strip()
    win_rate = to_float(best.get("test_win_rate"))
    expectation = to_float(best.get("test_expectation"))

    records: list[dict[str, Any]] = []
    if combo:
        conn = get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT dm, mc, buy_date, entry, stop, exit_price, ret
                    FROM history_replay
                    WHERE combo = %s AND period = %s
                    ORDER BY buy_date DESC, id DESC
                    """,
                    (combo, period),
                )
                raw_rows = cursor.fetchall()
                for row in raw_rows:
                    buy_date = to_date(row.get("buy_date"))
                    records.append(
                        {
                            "dm": str(row.get("dm") or "").strip(),
                            "mc": str(row.get("mc") or ""),
                            "buy_date": buy_date.isoformat() if buy_date else None,
                            "entry": _num(row.get("entry")),
                            "stop": _num(row.get("stop")),
                            "exit_price": _num(row.get("exit_price")),
                            "ret": _num(row.get("ret")),
                        }
                    )
        finally:
            conn.close()

    return JSONResponse(
        {
            "combo": combo or None,
            "period": period or None,
            "win_rate": win_rate,
            "expectation": expectation,
            "records": records,
        }
    )


@app.get("/api/kline")
def api_kline(dm: str, date: str) -> JSONResponse:
    """按需返回单只股票某买入日前后各30天的K线。"""
    buy_date = to_date(date)
    if not dm or buy_date is None:
        return JSONResponse({"dm": dm, "klines": []})
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            klines = _load_klines_window(cursor, dm, buy_date)
    finally:
        conn.close()
    return JSONResponse({"dm": dm, "klines": klines})


@app.get("/api/combos")
def api_combos() -> JSONResponse:
    """返回 combo_rank 全量达标组合胜率排行。"""
    ensure_combo_tables()
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT combo, period, test_win_rate, test_expectation, test_ratio,
                       test_sample, train_win_rate
                FROM combo_rank
                ORDER BY test_win_rate DESC, test_expectation DESC, test_sample DESC, id ASC
                """
            )
            rows = cursor.fetchall()
    finally:
        conn.close()

    combos: list[dict[str, Any]] = []
    for row in rows:
        combos.append(
            {
                "combo": str(row.get("combo") or "").strip(),
                "period": str(row.get("period") or "").strip(),
                "test_win_rate": _num(row.get("test_win_rate")),
                "test_expectation": _num(row.get("test_expectation")),
                "test_ratio": _num(row.get("test_ratio")),
                "test_sample": int(row.get("test_sample") or 0),
                "train_win_rate": _num(row.get("train_win_rate")),
            }
        )
    return JSONResponse({"combos": combos})


@app.get("/api/backtest")
def api_backtest(
    factors: str = "",
    period: str = "",
    limit: int = Query(BACKTEST_RECORD_DEFAULT, ge=1, le=BACKTEST_RECORD_MAX),
) -> JSONResponse:
    """手动回溯指定 2-3 因子组合（测试期），复用回踩买入 + 大盘过滤 + 止损 8%。"""
    parsed = _parse_factors(factors)
    period_name = str(period or "").strip()
    if parsed is None:
        return JSONResponse(
            {"error": "factors 需为 2 或 3 个已知因子，逗号分隔"},
            status_code=400,
        )
    if period_name not in _PERIOD_MAP:
        return JSONResponse(
            {"error": "period 需为 超短/短/中短/中"},
            status_code=400,
        )

    stats, records = _backtest_one_combo(parsed, period_name)
    key = combo_key(parsed)
    shown = records[: int(limit)]
    return JSONResponse(
        {
            "combo": key,
            "period": period_name,
            "test_win_rate": _round2(stats.test_win_rate),
            "test_expectation": _round2(stats.test_expectation),
            "test_ratio": _round_ratio(stats.test_ratio),
            "test_sample": stats.test_n,
            "records": [_serialize_backtest_record(r) for r in shown],
        }
    )


@app.get("/")
def index() -> FileResponse:
    return FileResponse(INDEX_HTML, media_type="text/html; charset=utf-8")


@app.get("/echarts.min.js")
def echarts_js() -> FileResponse:
    return FileResponse(PUBLIC_DIR / "echarts.min.js", media_type="application/javascript")


def _date_str(value: date | None) -> str | None:
    return value.isoformat() if value else None


def _jsonable(row: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in row.items():
        if isinstance(value, datetime):
            out[key] = value.strftime("%Y-%m-%d %H:%M:%S")
        elif isinstance(value, date):
            out[key] = value.isoformat()
        elif isinstance(value, Decimal):
            out[key] = float(value)
        else:
            out[key] = value
    return out


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
