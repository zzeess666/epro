"""同步股票列表：仅取按 dm 排序后的前 N 只（默认 100）。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from config.config import SYNC_STOCK_LIMIT
from src.api.mairui_client import MairuiClient
from src.db.connection import get_connection


def parse_stock_row(item: dict[str, Any]) -> dict[str, str] | None:
    raw_dm = str(item.get("dm") or "").strip()
    raw_jys = str(item.get("jys") or "").strip().upper()
    name = str(item.get("mc") or "").strip()
    if not raw_dm:
        return None
    if "." in raw_dm:
        dm, suffix = raw_dm.split(".", 1)
        if not raw_jys:
            raw_jys = suffix.strip().upper()
    else:
        dm = raw_dm
    dm = "".join(ch for ch in dm if ch.isdigit())
    if not dm:
        return None
    return {"dm": dm, "mc": name, "jys": raw_jys}


def run(limit: int | None = None) -> int:
    cap = SYNC_STOCK_LIMIT if limit is None else min(int(limit), SYNC_STOCK_LIMIT)
    client = MairuiClient()
    rows = client.get_stock_list()
    parsed: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in rows:
        stock = parse_stock_row(item)
        if stock is None or stock["dm"] in seen:
            continue
        seen.add(stock["dm"])
        parsed.append(stock)

    parsed.sort(key=lambda x: x["dm"])
    selected = parsed[:cap]
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.executemany(
                """
                REPLACE INTO stock_basic (dm, mc, jys, updated_at)
                VALUES (%s, %s, %s, %s)
                """,
                [(s["dm"], s["mc"], s["jys"], now) for s in selected],
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    print(
        f"[stock_list] API={len(rows)} 去重={len(parsed)} "
        f"入库={len(selected)} (SYNC_STOCK_LIMIT={cap})"
    )
    return len(selected)


if __name__ == "__main__":
    run()
