"""尾盘观察列表扫描器：扫全市场找出满足 Top3 组合的股票。

Top3 组合（写死，不从 combo_rank 动态读）：
  1. box_breakout+expma_golden+gap_up   （胜率 68.72%，样本 1397）
  2. box_breakout+expma_golden+second_breakout（胜率 67.97%，样本 1255）
  3. box_breakout+gap_up+second_breakout    （胜率 63.56%，样本 5647）

数据时效性：
  - 因子 flag：基于昨日收盘（factor_flag t=昨日）
  - 价格：基于今日最新行情（daily_kline t=今日）
  - gap_up：今日开盘 vs 昨日收盘
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from src.combo.combination_miner import load_index_bull_map
from src.db.connection import get_connection
from src.factor.factor_library import is_st_name, is_tradable_exchange
from src.strategy.base_strategy import to_date, to_float

# ------------------------------------------------------------------ #
# 常量
# ------------------------------------------------------------------ #

# 上证 / 深证 / 科创50 / 创业板 对应的 index_kline.code
_IDX_SH = "000001.SH"
_IDX_SZ = "399001.SZ"
_IDX_KC50 = "000688.SH"
_IDX_CYB = "399006.SZ"

_STABILITY = {
    "gap_up": "high",
    "box_breakout": "low",
    "expma_golden": "low",
    "second_breakout": "low",
}

TOP3_COMBOS = [
    {
        "combo": "box_breakout+expma_golden+gap_up",
        "win_rate": 68.72,
        "sample": 1397,
        "factors": ("box_breakout", "expma_golden", "gap_up"),
    },
    {
        "combo": "box_breakout+expma_golden+second_breakout",
        "win_rate": 67.97,
        "sample": 1255,
        "factors": ("box_breakout", "expma_golden", "second_breakout"),
    },
    {
        "combo": "box_breakout+gap_up+second_breakout",
        "win_rate": 63.56,
        "sample": 5647,
        "factors": ("box_breakout", "gap_up", "second_breakout"),
    },
]


# ------------------------------------------------------------------ #
# 工具
# ------------------------------------------------------------------ #

def _round2(value: float) -> float:
    if not value:
        return 0.0
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _to_float(v: Any) -> float | None:
    if v is None:
        return None
    if isinstance(v, float):
        return v
    if isinstance(v, int):
        return float(v)
    if isinstance(v, Decimal):
        return float(v)
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ------------------------------------------------------------------ #
# 数据加载
# ------------------------------------------------------------------ #

def _latest_trade_date(conn) -> date | None:
    """返回 factor_flag/daily_kline 最新交易日（两者取最新）。"""
    with conn.cursor() as c:
        c.execute("SELECT MAX(t) AS m FROM factor_flag")
        t1 = to_date((c.fetchone() or {}).get("m"))
        c.execute("SELECT MAX(t) AS m FROM daily_kline")
        t2 = to_date((c.fetchone() or {}).get("m"))
    latest = t1 if t1 is not None else t2
    if latest is None:
        return None
    # 取两者较大者
    if t2 is not None and t2 > latest:
        latest = t2
    return latest


def _prev_trade_date(conn, target: date) -> date | None:
    with conn.cursor() as c:
        c.execute("SELECT MAX(t) AS m FROM factor_flag WHERE t < %s", (target,))
        return to_date((c.fetchone() or {}).get("m"))


def _load_market_index_status(conn, day: date) -> dict[str, dict[str, Any]]:
    """返回四大指数当日 MA20 状态。"""
    codes = [_IDX_SH, _IDX_SZ, _IDX_KC50, _IDX_CYB]
    result = {}
    with conn.cursor() as c:
        placeholders = ",".join(["%s"] * len(codes))
        c.execute(
            f"SELECT code, c, ma20 FROM index_kline WHERE code IN ({placeholders}) AND t = %s",
            (*codes, day),
        )
        for row in c.fetchall():
            code = str(row["code"] or "").strip()
            close = _to_float(row["c"])
            ma20 = _to_float(row["ma20"])
            if close is not None and ma20 is not None:
                above = close > ma20
            else:
                above = False
            result[code] = {
                "close": _round2(close) if close is not None else None,
                "ma20": _round2(ma20) if ma20 is not None else None,
                "status": "above" if above else "below",
            }
    return result


def _market_bull(result: dict[str, dict[str, Any]]) -> bool:
    """任一指数在 MA20 上方即为多头。"""
    for code, info in result.items():
        if info.get("status") == "above":
            return True
    return False


def _load_yesterday_factor_flags(conn, prev_day: date) -> dict[str, set[str]]:
    """返回 prev_day 日期每只股票满足的因子集合。"""
    with conn.cursor() as c:
        c.execute(
            "SELECT dm, factor FROM factor_flag WHERE t = %s AND flag = 1",
            (prev_day,),
        )
        flags: dict[str, set[str]] = defaultdict(set)
        for row in c.fetchall():
            dm = str(row["dm"] or "").strip()
            factor = str(row["factor"] or "").strip()
            if dm and factor:
                flags[dm].add(factor)
    return dict(flags)


def _load_today_prices(conn, today: date) -> dict[str, dict[str, Any]]:
    """返回今日 K 线数据（O/H/L/C/PC）。"""
    with conn.cursor() as c:
        c.execute(
            "SELECT dm, o, h, l, c, pc FROM daily_kline WHERE t = %s",
            (today,),
        )
        prices: dict[str, dict[str, Any]] = {}
        for row in c.fetchall():
            dm = str(row["dm"] or "").strip()
            if not dm:
                continue
            o = _to_float(row["o"])
            h = _to_float(row["h"])
            l = _to_float(row["l"])
            c_val = _to_float(row["c"])
            pc = _to_float(row["pc"])
            prices[dm] = {
                "o": o, "h": h, "l": l, "c": c_val, "pc": pc,
            }
    return prices


def _load_prev_closes(conn, today: date, dms: list[str]) -> dict[str, float]:
    """返回昨日收盘价（用于计算 gap_up）。"""
    if not dms:
        return {}
    prev_day = _prev_trade_date(conn, today)
    if prev_day is None:
        return {}
    placeholders = ",".join(["%s"] * len(dms))
    with conn.cursor() as c:
        c.execute(
            f"SELECT dm, c FROM daily_kline WHERE t = %s AND dm IN ({placeholders})",
            (prev_day, *dms),
        )
        return {
            str(row["dm"] or "").strip(): _to_float(row["c"])
            for row in c.fetchall()
        }


def _load_basics(conn, dms: list[str]) -> dict[str, dict[str, Any]]:
    """返回股票基本信息（mc, jys）。"""
    if not dms:
        return {}
    placeholders = ",".join(["%s"] * len(dms))
    with conn.cursor() as c:
        c.execute(
            f"SELECT dm, mc, jys FROM stock_basic WHERE dm IN ({placeholders})",
            tuple(dms),
        )
        return {str(row["dm"] or "").strip(): row for row in c.fetchall()}


# ------------------------------------------------------------------ #
# 生成器
# ------------------------------------------------------------------ #

@dataclass
class WatchlistStock:
    dm: str
    mc: str
    jys: str
    close: float
    pct_change: float | None
    signals: list[str]
    stability: dict[str, str]


def generate(
    today: date | None = None,
) -> dict[str, Any]:
    """生成尾盘观察列表。返回结构化字典。"""

    conn = get_connection()
    try:
        # 确定交易日
        latest = _latest_trade_date(conn)
        if latest is None:
            return _empty_response("无交易日数据")
        day = today or latest

        # 昨日（信号计算基准）
        prev_day = _prev_trade_date(conn, day)
        if prev_day is None:
            return _empty_response(f"无 prev_day for {day}")

        # 1. 大盘过滤
        idx_status = _load_market_index_status(conn, day)
        is_bull = _market_bull(idx_status)

        # 2. 加载昨日因子
        yf_flags = _load_yesterday_factor_flags(conn, prev_day)

        # 3. 今日价格
        today_prices = _load_today_prices(conn, day)

        # 4. 加载基本信息
        all_dms = list(yf_flags.keys())
        basics = _load_basics(conn, all_dms)

        # 5. 昨日收盘（计算 gap_up 用）
        prev_closes = _load_prev_closes(conn, day, all_dms)

        # 6. 按组合筛选
        combos_result = []
        for combo_spec in TOP3_COMBOS:
            target_factors = set(combo_spec["factors"])
            matched_dms = []
            for dm, factors in yf_flags.items():
                if target_factors.issubset(factors):
                    matched_dms.append(dm)

            # ST / 非 tradable 过滤
            stocks = []
            for dm in matched_dms:
                basic = basics.get(dm, {})
                if not is_tradable_exchange(basic.get("jys")):
                    continue
                if is_st_name(basic.get("mc")):
                    continue

                price = today_prices.get(dm, {})
                close = price.get("c")
                if close is None or close <= 0:
                    continue

                prev_c = prev_closes.get(dm)

                # pct_change：今日收盘 vs 昨日收盘
                pct = None
                if close is not None and prev_c is not None and prev_c > 0:
                    pct = _round2((close - prev_c) / prev_c * 100.0)

                mc = str(basic.get("mc") or "")
                jys = str(basic.get("jys") or "")

                # 信号列表（直接取 factor_flag，不实时重算）
                stock_factors = yf_flags.get(dm, set())
                signals = [f for f in combo_spec["factors"] if f in stock_factors]
                stability = {f: _STABILITY.get(f, "low") for f in signals}

                stocks.append({
                    "dm": dm,
                    "mc": mc,
                    "jys": jys,
                    "close": _round2(close),
                    "pct_change": pct,
                    "signals": signals,
                    "stability": stability,
                })

            # 按涨跌幅降序
            stocks.sort(key=lambda r: (r["pct_change"] is None, -(r["pct_change"] or 0.0), r["dm"]))
            combos_result.append({
                "combo": combo_spec["combo"],
                "win_rate": combo_spec["win_rate"],
                "sample": combo_spec["sample"],
                "stocks": stocks,
            })

        generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        return {
            "date": day.isoformat(),
            "market_status": "bull" if is_bull else "bear",
            "market_index": {
                "sh": idx_status.get(_IDX_SH, {"close": None, "ma20": None, "status": "below"}),
                "sz": idx_status.get(_IDX_SZ, {"close": None, "ma20": None, "status": "below"}),
                "kc50": idx_status.get(_IDX_KC50, {"close": None, "ma20": None, "status": "below"}),
                "cyb": idx_status.get(_IDX_CYB, {"close": None, "ma20": None, "status": "below"}),
            },
            "combos": combos_result,
            "generated_at": generated_at,
        }
    finally:
        conn.close()


def _empty_response(msg: str) -> dict[str, Any]:
    return {
        "date": None,
        "market_status": "bear",
        "market_index": {},
        "combos": [],
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "_error": msg,
    }
