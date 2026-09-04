"""尾盘观察列表 API：GET /api/watchlist。"""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from src.screen.watchlist_generator import generate

router = APIRouter()


@router.get("/api/watchlist")
def api_watchlist(
    date: str | None = Query(None, description="指定交易日 YYYY-MM-DD，不指定则用最新"),
) -> JSONResponse:
    """返回尾盘观察列表（Top3 组合命中股票）。"""
    trade_date: date | None = None
    if date:
        from src.strategy.base_strategy import to_date
        trade_date = to_date(date)

    data: dict[str, Any] = generate(today=trade_date)

    # 清除内部错误字段
    data.pop("_error", None)
    return JSONResponse(data)
