#!/usr/bin/env python3
"""
日更同步脚本：新浪主用 + 麦蕊备用
用法:
  python sync_daily_sina.py              # 日更今日
  python sync_daily_sina.py --init        # 全历史初始化（用麦蕊）
  python sync_daily_sina.py --check       # 检查今日同步状态
"""

from __future__ import annotations

import sys
import csv
import time
import re
import pymysql
import argparse
import urllib.request
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.config import MAIRUI_API_BASE
from src.api.mairui_client import MairuiClient
from src.db.connection import get_connection

TODAY = date.today().isoformat()
CSV_PATH = f"/tmp/kline_{TODAY}.csv"


# ─── 新浪接口 ────────────────────────────────────────────

def dm_to_sina(dm: str, jys: str = "") -> str:
    """股票代码 → 新浪格式"""
    if jys == "SZ" or (not jys and not dm.startswith(("6", "5", "9", "7", "8"))):
        return "sz" + dm
    return "sh" + dm


def sina_to_dm(sina_code: str) -> str:
    """新浪格式 → 纯数字代码"""
    return sina_code[2:]  # 去掉 sh/sz 前缀


def fetch_sina_batch(codes: list[str]) -> dict[str, dict]:
    """批量获取新浪实时数据，返回 {sina_code: {o,c,h,l,v,a,date,pc}}"""
    if not codes:
        return {}
    url = f"https://hq.sinajs.cn/list={','.join(codes)}"
    try:
        req = urllib.request.Request(
            url,
            headers={
                "Referer": "https://finance.sina.com.cn",
                "User-Agent": "Mozilla/5.0",
            },
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            text = resp.read().decode("gbk", errors="replace")
    except Exception as e:
        print(f"  [sina] 网络错误: {e}")
        return {}

    result = {}
    for code in codes:
        m = re.search(rf'hq_str_{re.escape(code)}="([^"]+)"', text)
        if not m:
            continue
        fields = m.group(1).split(",")
        if len(fields) < 31:
            continue
        try:
            trade_date = fields[30]
            close = float(fields[3])
            if trade_date != TODAY or close <= 0:
                continue
            result[code] = {
                "o": float(fields[1]),
                "c": close,
                "h": float(fields[4]),
                "l": float(fields[5]),
                "v": int(float(fields[8])),
                "a": float(fields[9]),
                "date": trade_date,
                "pc": float(fields[2]),  # 昨收价
            }
        except (ValueError, IndexError):
            continue
    return result


# ─── 麦蕊备用接口 ────────────────────────────────────────

def fetch_mairui_fallback(dm: str, jys: str) -> dict | None:
    """麦蕊备用：获取单只股票今日K线"""
    client = MairuiClient(base_url=MAIRUI_API_BASE)
    try:
        rows = client.get_daily_kline(dm, jys, TODAY, TODAY, limit=10)
        for row in rows:
            if row.get("t") == TODAY:
                return {
                    "o": row.get("o"),
                    "c": row.get("c"),
                    "h": row.get("h"),
                    "l": row.get("l"),
                    "v": row.get("v"),
                    "a": row.get("a"),
                    "date": row.get("t"),
                }
    except Exception:
        pass
    return None


# ─── 数据库写入 ─────────────────────────────────────────

def write_to_csv(rows: list[tuple]) -> None:
    """追加写入CSV"""
    mode = "w" if not Path(CSV_PATH).exists() else "a"
    with open(CSV_PATH, mode, newline="") as f:
        writer = csv.writer(f, delimiter="\t")
        if mode == "w":
            writer.writerow(["dm", "t", "o", "c", "h", "l", "v", "a", "pc"])
        writer.writerows(rows)


def load_csv_to_db() -> int:
    """CSV → MySQL（分批提交，避免锁超时）"""
    if not Path(CSV_PATH).exists():
        return 0
    conn = get_connection()
    rows = []
    with open(CSV_PATH, "r") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            rows.append(
                (
                    row["dm"],
                    row["t"],
                    float(row["o"]),
                    float(row["c"]),
                    float(row["h"]),
                    float(row["l"]),
                    int(float(row["v"])),
                    float(row["a"]),
                    float(row["pc"]) if row.get("pc") else None,
                )
            )

    # 去重（已有今日数据则跳过）
    cur = conn.cursor()
    cur.execute("SELECT dm FROM daily_kline WHERE t=%s", (TODAY,))
    existing = set(r["dm"] for r in cur.fetchall())
    rows = [r for r in rows if r[0] not in existing]
    cur.close()

    if not rows:
        conn.close()
        return 0

    BATCH = 200
    inserted = 0
    for i in range(0, len(rows), BATCH):
        batch = rows[i : i + BATCH]
        cur2 = conn.cursor()
        cur2.executemany(
            "INSERT IGNORE INTO daily_kline (dm,t,o,c,h,l,v,a,pc) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            batch,
        )
        conn.commit()
        cur2.close()
        inserted += len(batch)
        print(f"  [db] 写入 {inserted}/{len(rows)}")

    conn.close()
    return inserted


# ─── 今日同步主流程 ─────────────────────────────────────

def sync_daily() -> dict:
    """新浪主用 + 麦蕊备用，返回同步统计"""
    print(f"\n{'='*60}")
    print(f"日更同步 {TODAY}  新浪主用 + 麦蕊备用")
    print(f"{'='*60}")

    conn = get_connection()
    cur = conn.cursor()

    # 查今日已同步
    cur.execute("SELECT dm FROM daily_kline WHERE t=%s", (TODAY,))
    done = set(r["dm"] for r in cur.fetchall())

    # 查所有股票
    cur.execute("SELECT dm, jys FROM stock_basic")
    all_stocks = [(row["dm"], row.get("jys") or "") for row in cur.fetchall()]
    cur.close()
    conn.close()

    pending = [s for s in all_stocks if s[0] not in done]
    print(f"总股票: {len(all_stocks)}  今日已同步: {len(done)}  待同步: {len(pending)}")

    if not pending:
        print("今日数据已完整，无需同步")
        return {"done": len(done), "pending": 0, "sina_ok": 0, "mairui_ok": 0, "failed": 0}

    # ── Step 1: 新浪批量拉取 ──
    print("\n[Step 1] 新浪批量拉取...")
    Path(CSV_PATH).unlink(missing_ok=True)
    BATCH = 50
    sina_ok = 0
    mairui_ok = 0
    failed = 0
    t0 = time.time()

    for batch_idx in range(0, len(pending), BATCH):
        batch = pending[batch_idx : batch_idx + BATCH]
        sina_codes = [dm_to_sina(dm, jys) for dm, jys in batch]

        sina_data = fetch_sina_batch(sina_codes)

        batch_rows = []
        for dm, jys in batch:
            sina_code = dm_to_sina(dm, jys)
            if sina_code in sina_data:
                d = sina_data[sina_code]
                batch_rows.append((dm, d["date"], d["o"], d["c"], d["h"], d["l"], d["v"], d["a"], d.get("pc")))
                sina_ok += 1
            else:
                # 麦蕊备用
                d = fetch_mairui_fallback(dm, jys)
                if d:
                    batch_rows.append((dm, d["date"], d["o"], d["c"], d["h"], d["l"], d["v"], d["a"], None))
                    mairui_ok += 1
                else:
                    failed += 1

        if batch_rows:
            write_to_csv(batch_rows)

        elapsed = time.time() - t0
        pct = (batch_idx + BATCH) * 100 / len(pending)
        rate = (batch_idx + BATCH) / elapsed if elapsed > 0 else 1
        eta = (len(pending) - batch_idx - BATCH) / rate if rate > 0 else 0
        print(
            f"  批次{batch_idx//BATCH+1}/{(len(pending)+BATCH-1)//BATCH} "
            f"| {pct:.1f}% | 新浪{sina_ok} 麦蕊{mairui_ok} 失败{failed} | "
            f"{rate:.0f}票/秒 | 剩余{eta:.0f}秒"
        )

    print(f"\n[Step 2] CSV → MySQL...")
    inserted = load_csv_to_db()

    total = sina_ok + mairui_ok
    elapsed = time.time() - t0
    print(f"\n✅ 完成！共 {inserted} 条（新浪{sina_ok} + 麦蕊{mairui_ok}），"
          f"失败 {failed}，耗时 {time.time()-t0:.0f}秒")

    return {"done": len(done) + inserted, "pending": failed,
             "sina_ok": sina_ok, "mairui_ok": mairui_ok, "failed": failed}


def check_status() -> None:
    """检查今日同步状态"""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) AS cnt FROM daily_kline WHERE t=%s", (TODAY,))
    today_count = cur.fetchone()["cnt"]
    cur.execute("SELECT COUNT(*) AS cnt FROM stock_basic")
    total = cur.fetchone()["cnt"]
    cur.close()
    conn.close()

    pct = today_count * 100 / total if total > 0 else 0
    status = "✅ 完整" if today_count >= total * 0.99 else ("⚠️ 部分" if today_count > 100 else "❌ 缺失严重")
    print(f"\n{TODAY} 同步状态: {today_count}/{total} ({pct:.1f}%) {status}")


def main() -> int:
    parser = argparse.ArgumentParser(description="日更同步：新郎主用+麦蕊备用")
    parser.add_argument("--check", action="store_true", help="仅检查状态")
    args = parser.parse_args()

    if args.check:
        check_status()
        return 0

    result = sync_daily()
    return 0 if result["failed"] < 50 else 1  # 失败多则报错


if __name__ == "__main__":
    raise SystemExit(main())
