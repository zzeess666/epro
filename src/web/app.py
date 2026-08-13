"""FastAPI：推荐列表 / 跟踪状态 / 首页。"""

from __future__ import annotations

import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse

from src.track.track_service import list_watches, load_latest_recommend, now_cn

PUBLIC_DIR = ROOT / "public"
INDEX_HTML = PUBLIC_DIR / "index.html"

app = FastAPI(title="EPro", docs_url=None, redoc_url=None)


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


@app.get("/")
def index() -> FileResponse:
    return FileResponse(INDEX_HTML, media_type="text/html; charset=utf-8")


def _date_str(value: date | None) -> str | None:
    return value.isoformat() if value else None


def _jsonable(row: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in row.items():
        if isinstance(value, datetime):
            out[key] = value.strftime("%Y-%m-%d %H:%M:%S")
        elif isinstance(value, date):
            out[key] = value.isoformat()
        else:
            out[key] = value
    return out


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
