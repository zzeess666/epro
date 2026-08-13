"""跟踪清单生成 + 盘中检查 + 尾盘判断。仅处理 track_watch 内股票（≤3）。"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Optional
from zoneinfo import ZoneInfo

from src.api.mairui_client import MairuiApiError, MairuiClient
from src.db.connection import get_connection
from src.recommend.recommend_engine import ensure_tables as ensure_recommend_tables

MAX_WATCH = 3
STATUS_WATCHING = "观察中"
STATUS_PASS = "达标"
STATUS_FAIL = "不达标"
VOLUME_RATIO_MIN = 1.0
TAIL_START = time(14, 30)
TAIL_END = time(15, 0)
try:
    CN_TZ = ZoneInfo("Asia/Shanghai")
except Exception:
    CN_TZ = None

_CREATE_TRACK_WATCH = """
CREATE TABLE IF NOT EXISTS track_watch (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  dm VARCHAR(10) NOT NULL,
  track_date DATE NOT NULL COMMENT '跟踪日期',
  status VARCHAR(20) DEFAULT '观察中' COMMENT '观察中/达标/不达标',
  entry_price DECIMAL(10,2) COMMENT '建议买入价',
  stop_loss DECIMAL(10,2) COMMENT '止损价',
  current_price DECIMAL(10,2) COMMENT '最新价',
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  KEY idx_date (track_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
"""


def ensure_tables() -> None:
    ensure_recommend_tables()
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(_CREATE_TRACK_WATCH)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def run(track_date: Optional[date] = None, now: Optional[datetime] = None) -> dict[str, Any]:
    """生成跟踪清单、盘中更新价格并判断达标；尾盘时段输出提醒。"""
    ensure_tables()
    now_dt = now_cn(now)
    watches = generate_watchlist(track_date=track_date)
    day = track_date or _resolve_check_date(watches, now_dt.date())
    updated = check_intraday(day, now=now_dt)
    alerts: list[str] = []
    if is_tail_session(now_dt):
        alerts = emit_tail_alerts(day)
    return {"track_date": day, "watches": watches, "updated": updated, "alerts": alerts}


def generate_watchlist(track_date: Optional[date] = None) -> list[dict[str, Any]]:
    """读取最新 recommend_result，写入次日 track_watch（最多 3 只）。"""
    ensure_tables()
    recs, rec_day = load_latest_recommend()
    if not recs or rec_day is None:
        print("[track] 无推荐数据，请先运行 scripts/run_recommend.py")
        return []

    day = track_date or next_trade_date(rec_day)
    print(f"[track] 推荐日={rec_day} 跟踪日={day} 候选={len(recs)}")

    existing = {(w["dm"], w["track_date"]) for w in _load_watches(day)}
    inserted: list[dict[str, Any]] = []
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            for rec in recs[:MAX_WATCH]:
                key = (rec["dm"], day)
                if key in existing:
                    continue
                cursor.execute(
                    """
                    INSERT INTO track_watch
                      (dm, track_date, status, entry_price, stop_loss, updated_at)
                    VALUES (%s, %s, %s, %s, %s, NOW())
                    """,
                    (
                        rec["dm"],
                        day,
                        STATUS_WATCHING,
                        rec["entry_price"],
                        rec["stop_loss"],
                    ),
                )
                inserted.append(
                    {
                        "dm": rec["dm"],
                        "mc": rec.get("mc"),
                        "track_date": day,
                        "status": STATUS_WATCHING,
                        "entry_price": rec["entry_price"],
                        "stop_loss": rec["stop_loss"],
                    }
                )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    if inserted:
        print(f"[track] 新写入 {len(inserted)} 条")
        for row in inserted:
            print(
                f"[track] 观察 {row['dm']} 买入={row['entry_price']} 止损={row['stop_loss']}"
            )
    else:
        print("[track] 跟踪清单已存在，跳过写入")
    return list_watches(day)


def check_intraday(track_date: Optional[date] = None, now: Optional[datetime] = None) -> list[dict[str, Any]]:
    """仅遍历当日观察中的跟踪股（≤3），拉最新价并更新状态。"""
    ensure_tables()
    now_dt = now_cn(now)
    day = track_date or now_dt.date()
    watching = _load_watches(day, status=STATUS_WATCHING)[:MAX_WATCH]
    if not watching:
        print(f"[track] {day} 无观察中标的")
        return []

    after_tail = now_dt.time() >= TAIL_START
    client = MairuiClient()
    updated: list[dict[str, Any]] = []
    for row in watching:
        dm = row["dm"]
        try:
            quote = client.get_realtime_quote(dm)
        except (MairuiApiError, ValueError) as exc:
            print(f"[track] {dm} 行情失败: {exc}")
            continue
        price = _quote_price(quote)
        if price is None:
            print(f"[track] {dm} 无最新价，跳过")
            continue
        volume_up = _is_volume_up(dm, quote)
        status = _judge_status(
            price=price,
            entry_price=row.get("entry_price"),
            stop_loss=row.get("stop_loss"),
            after_1430=after_tail,
            volume_up=volume_up,
        )
        _update_watch(row["id"], price, status)
        out = {
            **row,
            "current_price": _round2(price),
            "status": status,
            "volume_up": volume_up,
        }
        updated.append(out)
        print(
            f"[track] 盘中 {dm} 最新价={_round2(price)} 状态={status}"
            f"{' 放量' if volume_up else ''}"
        )
    return updated


def emit_tail_alerts(track_date: Optional[date] = None) -> list[str]:
    """输出达标股票提醒文本（stdout + 返回列表供 Web）。"""
    day = track_date or now_cn().date()
    passed = [w for w in list_watches(day) if w.get("status") == STATUS_PASS]
    if not passed:
        print("[track] 尾盘无达标标的")
        return []

    lines = ["[track] ===== 尾盘提醒 ====="]
    for row in passed:
        name = row.get("mc") or "-"
        line = (
            f"[track] 达标 {row['dm']} {name} "
            f"最新价={_fmt_price(row.get('current_price'))} "
            f"建议买入={_fmt_price(row.get('entry_price'))} "
            f"止损={_fmt_price(row.get('stop_loss'))}"
        )
        lines.append(line)
    lines.append("[track] ====================")
    for line in lines:
        print(line)
    return lines


def list_watches(track_date: Optional[date] = None) -> list[dict[str, Any]]:
    if track_date is not None:
        return _load_watches(track_date)[:MAX_WATCH]
    today = now_cn().date()
    rows = _load_watches(today)[:MAX_WATCH]
    if rows:
        return rows
    latest = _latest_track_date()
    if latest is None:
        return []
    return _load_watches(latest)[:MAX_WATCH]


def _latest_track_date() -> Optional[date]:
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT MAX(track_date) AS t FROM track_watch")
            row = cursor.fetchone()
    finally:
        conn.close()
    return _to_date(row["t"] if row else None)


def load_latest_recommend() -> tuple[list[dict[str, Any]], Optional[date]]:
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT MAX(t) AS t FROM recommend_result")
            row = cursor.fetchone()
            day = _to_date(row["t"] if row else None)
            if day is None:
                return [], None
            cursor.execute(
                """
                SELECT r.t, r.dm, r.strategy, r.score, r.reason,
                       r.entry_price, r.stop_loss, r.position_pct, b.mc
                FROM recommend_result r
                LEFT JOIN stock_basic b ON b.dm = r.dm
                WHERE r.t = %s
                ORDER BY r.score DESC, r.dm
                LIMIT %s
                """,
                (day, MAX_WATCH),
            )
            rows = cursor.fetchall()
    finally:
        conn.close()
    return [_normalize_recommend(r) for r in rows], day


def next_trade_date(day: date) -> date:
    nxt = day + timedelta(days=1)
    while nxt.weekday() >= 5:
        nxt += timedelta(days=1)
    return nxt


def is_tail_session(now: Optional[datetime] = None) -> bool:
    t = now_cn(now).time()
    return TAIL_START <= t <= TAIL_END


def _load_watches(day: date, status: Optional[str] = None) -> list[dict[str, Any]]:
    sql = """
        SELECT w.id, w.dm, w.track_date, w.status, w.entry_price,
               w.stop_loss, w.current_price, w.updated_at, b.mc
        FROM track_watch w
        LEFT JOIN stock_basic b ON b.dm = w.dm
        WHERE w.track_date = %s
    """
    params: list[Any] = [day]
    if status:
        sql += " AND w.status = %s"
        params.append(status)
    sql += " ORDER BY w.id LIMIT %s"
    params.append(MAX_WATCH)
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(sql, params)
            rows = cursor.fetchall()
    finally:
        conn.close()
    return [_normalize_watch(r) for r in rows]


def _update_watch(watch_id: int, price: float, status: str) -> None:
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE track_watch
                SET current_price = %s, status = %s, updated_at = NOW()
                WHERE id = %s
                """,
                (_round2(price), status, watch_id),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _judge_status(
    price: float,
    entry_price: Optional[float],
    stop_loss: Optional[float],
    after_1430: bool,
    volume_up: bool,
) -> str:
    if stop_loss is not None and price <= float(stop_loss):
        return STATUS_FAIL
    if (
        after_1430
        and entry_price is not None
        and price >= float(entry_price)
        and volume_up
    ):
        return STATUS_PASS
    return STATUS_WATCHING


def _is_volume_up(dm: str, quote: dict[str, Any]) -> bool:
    lb = _to_float(quote.get("lb"))
    if lb is not None:
        return lb >= VOLUME_RATIO_MIN
    cur_v = _to_float(quote.get("v"))
    prev_v = _prev_volume(dm)
    if cur_v is None or prev_v is None or prev_v <= 0:
        return False
    # 实时 v 为万手，日K v 为手
    return (cur_v * 10000.0) >= prev_v


def _prev_volume(dm: str) -> Optional[float]:
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT v FROM daily_kline WHERE dm = %s ORDER BY t DESC LIMIT 1",
                (dm,),
            )
            row = cursor.fetchone()
    finally:
        conn.close()
    if not row:
        return None
    return _to_float(row.get("v"))


def _quote_price(quote: dict[str, Any]) -> Optional[float]:
    for key in ("p", "price", "c"):
        val = _to_float(quote.get(key))
        if val is not None and val > 0:
            return val
    return None


def _resolve_check_date(watches: list[dict[str, Any]], today: date) -> date:
    if watches:
        day = watches[0].get("track_date")
        if isinstance(day, date):
            return day
    return today


def now_cn(now: Optional[datetime] = None) -> datetime:
    if now is None:
        return datetime.now(CN_TZ) if CN_TZ is not None else datetime.now()
    if now.tzinfo is None:
        return now.replace(tzinfo=CN_TZ) if CN_TZ is not None else now
    return now.astimezone(CN_TZ) if CN_TZ is not None else now


def _normalize_recommend(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "t": _to_date(row.get("t")),
        "dm": row.get("dm"),
        "mc": row.get("mc"),
        "strategy": row.get("strategy"),
        "score": _to_float(row.get("score")),
        "reason": row.get("reason"),
        "entry_price": _to_float(row.get("entry_price")),
        "stop_loss": _to_float(row.get("stop_loss")),
        "position_pct": _to_float(row.get("position_pct")),
    }


def _normalize_watch(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row.get("id"),
        "dm": row.get("dm"),
        "mc": row.get("mc"),
        "track_date": _to_date(row.get("track_date")),
        "status": row.get("status") or STATUS_WATCHING,
        "entry_price": _to_float(row.get("entry_price")),
        "stop_loss": _to_float(row.get("stop_loss")),
        "current_price": _to_float(row.get("current_price")),
        "updated_at": _to_datetime_str(row.get("updated_at")),
    }


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


def _to_datetime_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    return str(value)


def _to_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _round2(value: float) -> float:
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _fmt_price(value: Any) -> str:
    num = _to_float(value)
    if num is None:
        return "-"
    return f"{_round2(num):.2f}"
