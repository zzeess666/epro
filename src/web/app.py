"""FastAPI：推荐列表 / 跟踪状态 / 历史回放 / 首页。"""

from __future__ import annotations

import base64
import os
import sys
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from src.db.connection import get_connection
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
