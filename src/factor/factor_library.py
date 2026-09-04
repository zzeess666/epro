"""因子库：每天每只股票本地计算指标（0/1），写入 factor_flag。

只用当日及之前的 K 线，不调用麦蕊 MA/MACD 接口。flag=1 才落库（缺省视为 0）。
"""

from __future__ import annotations

from typing import Any, Optional

from src.db.connection import get_connection
from src.strategy.base_strategy import normalize_kline
from src.strategy.strategy_a import StrategyA

# 用户指定（必须）+ 架构师补充
FACTOR_NAMES: tuple[str, ...] = (
    "macd_golden",
    "macd_second_golden",  # MACD 零轴下方第二次金叉
    "gap_up",
    "one_yang_3ma",
    "ma_bull",
    "above_ma20",
    "ma5_cross_10",
    "second_breakout",
    "shrink_pullback",
    "volume_ratio_high",
    "new_high_20",
    "limit_up",
    "expma_golden",
    "box_breakout",
    "kline_reversal",
)

USER_FACTORS: tuple[str, ...] = ("macd_golden", "gap_up", "one_yang_3ma")

MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9
EXPMA_FAST = 21
EXPMA_SLOW = 55
NEAR_MA10_PCT = 0.02
NEAR_MA20_PCT = 0.03
SHRINK_VOL_RATIO = 0.60
VOLUME_RATIO_HIGH = 1.5
LIMIT_UP_PCT = 0.095
BOX_LOOKBACK = 30
BOX_RANGE_PCT = 0.30
HAMMER_SHADOW_RATIO = 2.0
HAMMER_LOOKBACK = 10
HAMMER_DECLINE_PCT = 0.08
INSERT_CHUNK = 1000

_CREATE_FACTOR_FLAG = """
CREATE TABLE IF NOT EXISTS factor_flag (
  dm VARCHAR(10) NOT NULL,
  t DATE NOT NULL,
  factor VARCHAR(30) NOT NULL COMMENT '指标名',
  flag TINYINT NOT NULL DEFAULT 0 COMMENT '0/1',
  PRIMARY KEY (dm, t, factor),
  KEY idx_t_factor (t, factor)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
"""

_strategy_a = StrategyA()


def ensure_tables() -> None:
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(_CREATE_FACTOR_FLAG)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def sma_series(closes: list[Optional[float]], window: int) -> list[Optional[float]]:
    """按日期升序的收盘价 SMA；仅用到当日为止的有效收盘，样本不足为 None。"""
    result: list[Optional[float]] = [None] * len(closes)
    running: list[float] = []
    for i, close in enumerate(closes):
        if close is None:
            continue
        running.append(float(close))
        if len(running) >= window:
            result[i] = sum(running[-window:]) / window
    return result


def ema_series(values: list[Optional[float]], period: int) -> list[Optional[float]]:
    """EMA：前 period 个有效值用 SMA 做种子，之后递推。跳过 None，不看未来。"""
    result: list[Optional[float]] = [None] * len(values)
    if period <= 0:
        return result
    k = 2.0 / (period + 1.0)
    acc = 0.0
    count = 0
    ema_val: Optional[float] = None
    for i, raw in enumerate(values):
        if raw is None:
            continue
        value = float(raw)
        if ema_val is None:
            acc += value
            count += 1
            if count == period:
                ema_val = acc / period
                result[i] = ema_val
            continue
        ema_val = value * k + ema_val * (1.0 - k)
        result[i] = ema_val
    return result


def macd_diff_dea(
    closes: list[Optional[float]],
) -> tuple[list[Optional[float]], list[Optional[float]]]:
    """本地 MACD：DIFF = EMA12 - EMA26，DEA = EMA(DIFF, 9)。"""
    ema_fast = ema_series(closes, MACD_FAST)
    ema_slow = ema_series(closes, MACD_SLOW)
    diff: list[Optional[float]] = [None] * len(closes)
    for i in range(len(closes)):
        if ema_fast[i] is None or ema_slow[i] is None:
            continue
        diff[i] = ema_fast[i] - ema_slow[i]
    dea = ema_series(diff, MACD_SIGNAL)
    return diff, dea


def _avg_volume(klines: list[dict[str, Any]], start: int, end: int) -> Optional[float]:
    if start < 0 or end > len(klines) or end <= start:
        return None
    total = 0.0
    for i in range(start, end):
        vol = klines[i]["v"]
        if vol is None:
            return None
        total += float(vol)
    return total / (end - start)


def _is_yang(bar: dict[str, Any]) -> bool:
    open_p = bar.get("o")
    close = bar.get("c")
    return open_p is not None and close is not None and close > open_p


def _is_yin(bar: dict[str, Any]) -> bool:
    open_p = bar.get("o")
    close = bar.get("c")
    return open_p is not None and close is not None and close < open_p


def _is_hammer(today: dict[str, Any], close_n_ago: Optional[float]) -> bool:
    """锤形线：阳线、下影线 > 实体×2，且近 N 日累计跌幅超过阈值。"""
    if not _is_yang(today):
        return False
    open_p = today["o"]
    close = today["c"]
    low = today["l"]
    if low is None or close_n_ago is None or close_n_ago <= 0:
        return False
    body = float(close) - float(open_p)
    if body <= 0:
        return False
    lower_shadow = float(open_p) - float(low)
    if lower_shadow <= body * HAMMER_SHADOW_RATIO:
        return False
    return (float(close_n_ago) - float(close)) / float(close_n_ago) > HAMMER_DECLINE_PCT


def _is_bullish_engulfing(today: dict[str, Any], prev: dict[str, Any]) -> bool:
    """看涨吞没：今日阳线实体吞没昨日阴线实体。"""
    if not _is_yang(today) or not _is_yin(prev):
        return False
    today_open = today["o"]
    today_close = today["c"]
    prev_open = prev["o"]
    prev_close = prev["c"]
    if None in (today_open, today_close, prev_open, prev_close):
        return False
    return today_open <= prev_close and today_close >= prev_open


def _is_piercing_line(today: dict[str, Any], prev: dict[str, Any]) -> bool:
    """曙光初现：今日阳线低开低于昨低，收盘站上昨日实体中点。"""
    if not _is_yang(today):
        return False
    today_open = today["o"]
    today_close = today["c"]
    prev_open = prev["o"]
    prev_close = prev["c"]
    prev_low = prev["l"]
    if None in (today_open, today_close, prev_open, prev_close, prev_low):
        return False
    if today_open >= prev_low:
        return False
    midpoint = (float(prev_open) + float(prev_close)) / 2.0
    return float(today_close) > midpoint


def _is_kline_reversal(today: dict[str, Any], prev: Optional[dict[str, Any]], close_n_ago: Optional[float]) -> bool:
    if _is_hammer(today, close_n_ago):
        return True
    if prev is None:
        return False
    return _is_bullish_engulfing(today, prev) or _is_piercing_line(today, prev)


def _prepare_bars(klines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """本地回填 MA，供二次突破等复用；不读接口、不用未来数据。"""
    closes = [bar["c"] for bar in klines]
    ma5 = sma_series(closes, 5)
    ma10 = sma_series(closes, 10)
    ma20 = sma_series(closes, 20)
    prepared: list[dict[str, Any]] = []
    for i, bar in enumerate(klines):
        row = dict(bar)
        row["ma5"] = ma5[i]
        row["ma10"] = ma10[i]
        row["ma20"] = ma20[i]
        prepared.append(row)
    return prepared


def compute_factor_flags(klines: list[dict[str, Any]]) -> list[dict[str, int]]:
    """对升序 K 线逐日计算全部因子。第 i 日只用 klines[0..i]。"""
    n = len(klines)
    flags: list[dict[str, int]] = [{name: 0 for name in FACTOR_NAMES} for _ in range(n)]
    if n == 0:
        return flags

    bars = _prepare_bars(klines)
    closes = [bar["c"] for bar in bars]
    diff, dea = macd_diff_dea(closes)
    expma21 = ema_series(closes, EXPMA_FAST)
    expma55 = ema_series(closes, EXPMA_SLOW)

    for i, today in enumerate(bars):
        close = today["c"]
        open_p = today["o"]
        low = today["l"]
        volume = today["v"]
        ma5 = today["ma5"]
        ma10 = today["ma10"]
        ma20 = today["ma20"]
        row = flags[i]

        if i >= 1:
            prev = bars[i - 1]
            if open_p is not None and prev["h"] is not None and open_p > prev["h"]:
                row["gap_up"] = 1

            prev_close = today["pc"] if today.get("pc") is not None else prev["c"]
            if (
                close is not None
                and prev_close is not None
                and prev_close > 0
                and (close - prev_close) / prev_close >= LIMIT_UP_PCT
            ):
                row["limit_up"] = 1

            if (
                ma5 is not None
                and ma10 is not None
                and prev["ma5"] is not None
                and prev["ma10"] is not None
                and ma5 > ma10
                and prev["ma5"] <= prev["ma10"]
            ):
                row["ma5_cross_10"] = 1

        if (
            diff[i] is not None
            and dea[i] is not None
            and i >= 1
            and diff[i - 1] is not None
            and dea[i - 1] is not None
            and diff[i] > dea[i]
            and diff[i - 1] <= dea[i - 1]
        ):
            row["macd_golden"] = 1

        # MACD 零轴下方第二次金叉
        # 条件: 今天 DIF 上穿 DEA 且 DIF < 0（零轴下方）
        #       且 30-60 天前有过金叉（第一次）
        #       且中间（30 天内）有过死叉
        if (
            diff[i] is not None
            and dea[i] is not None
            and i >= 60
            and diff[i] > dea[i]
            and diff[i] < 0  # 零轴下方（关键！）
            and diff[i - 1] is not None
            and dea[i - 1] is not None
            and diff[i - 1] <= dea[i - 1]
        ):
            # 30 天内找死叉
            has_death = False
            for j in range(i - 1, max(i - 30, 0), -1):
                if diff[j] is None or dea[j] is None or j < 1:
                    continue
                if diff[j - 1] is None or dea[j - 1] is None:
                    continue
                if diff[j] < dea[j] and diff[j - 1] >= dea[j - 1]:
                    has_death = True
                    break
            # 30-60 天前找金叉
            if has_death:
                for j in range(i - 30, max(i - 60, 0), -1):
                    if diff[j] is None or dea[j] is None or j < 1:
                        continue
                    if diff[j - 1] is None or dea[j - 1] is None:
                        continue
                    if diff[j] > dea[j] and diff[j - 1] <= dea[j - 1]:
                        row["macd_second_golden"] = 1
                        break

        if ma5 is not None and ma10 is not None and ma20 is not None and ma5 > ma10 > ma20:
            row["ma_bull"] = 1

        if close is not None and ma20 is not None and close > ma20:
            row["above_ma20"] = 1

        is_yang = close is not None and open_p is not None and close > open_p
        if is_yang and ma5 is not None and ma10 is not None and ma20 is not None:
            stacked = close > ma5 > ma10 > ma20
            pierced = (
                low is not None
                and low < ma5
                and low < ma10
                and low < ma20
                and close > ma5
                and close > ma10
                and close > ma20
            )
            if stacked or pierced:
                row["one_yang_3ma"] = 1

        if i >= 19 and close is not None:
            prev_closes = [bars[j]["c"] for j in range(i - 19, i)]
            valid_prev = [float(v) for v in prev_closes if v is not None]
            if len(valid_prev) == 19 and close > max(valid_prev):
                row["new_high_20"] = 1

        if i >= 5 and volume is not None:
            avg_vol = _avg_volume(bars, i - 5, i)
            if avg_vol is not None and avg_vol > 0:
                ratio = volume / avg_vol
                if ratio > VOLUME_RATIO_HIGH:
                    row["volume_ratio_high"] = 1
                if ratio < SHRINK_VOL_RATIO and close is not None:
                    near_ma10 = (
                        ma10 is not None
                        and ma10 > 0
                        and abs(close - ma10) / ma10 <= NEAR_MA10_PCT
                    )
                    near_ma20 = (
                        ma20 is not None
                        and ma20 > 0
                        and abs(close - ma20) / ma20 <= NEAR_MA20_PCT
                    )
                    if near_ma10 or near_ma20:
                        row["shrink_pullback"] = 1

        if i >= _strategy_a.min_bars - 1:
            signal = _strategy_a.evaluate(str(today.get("dm") or ""), bars, i)
            if signal is not None:
                row["second_breakout"] = 1

        if (
            i >= 1
            and expma21[i] is not None
            and expma55[i] is not None
            and expma21[i - 1] is not None
            and expma55[i - 1] is not None
            and expma21[i] > expma55[i]
            and expma21[i - 1] <= expma55[i - 1]
        ):
            row["expma_golden"] = 1

        if i >= BOX_LOOKBACK and close is not None and volume is not None:
            highs = []
            lows = []
            box_ok = True
            for j in range(i - BOX_LOOKBACK, i):
                high_j = bars[j]["h"]
                low_j = bars[j]["l"]
                if high_j is None or low_j is None:
                    box_ok = False
                    break
                highs.append(float(high_j))
                lows.append(float(low_j))
            if box_ok and highs and lows:
                hh = max(highs)
                ll = min(lows)
                avg_vol = _avg_volume(bars, i - 5, i)
                if (
                    ll > 0
                    and (hh - ll) / ll < BOX_RANGE_PCT
                    and close > hh
                    and avg_vol is not None
                    and avg_vol > 0
                    and volume > avg_vol * VOLUME_RATIO_HIGH
                ):
                    row["box_breakout"] = 1

        prev_bar = bars[i - 1] if i >= 1 else None
        close_n_ago = bars[i - HAMMER_LOOKBACK]["c"] if i >= HAMMER_LOOKBACK else None
        if _is_kline_reversal(today, prev_bar, close_n_ago):
            row["kline_reversal"] = 1

    return flags


def load_stock_codes(limit: int | None = None) -> list[str]:
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            sql = "SELECT dm FROM stock_basic ORDER BY dm"
            if limit is not None and int(limit) > 0:
                cursor.execute(sql + " LIMIT %s", (int(limit),))
            else:
                cursor.execute(sql)
            return [row["dm"] for row in cursor.fetchall()]
    finally:
        conn.close()


def load_klines(dm: str, cursor=None, recent_days: int | None = None) -> list[dict[str, Any]]:
    """recent_days=None 表示全量；指定天数则只加载最近 N 天（加速日更）"""
    own = cursor is None
    conn = None
    if own:
        conn = get_connection()
        cursor = conn.cursor()
    try:
        if recent_days:
            cursor.execute(
                """
                SELECT t, o, h, l, c, v, a, pc, ma5, ma10, ma20, ma60
                FROM daily_kline
                WHERE dm = %s
                ORDER BY t DESC
                LIMIT %s
                """,
                (dm, recent_days),
            )
            rows = cursor.fetchall()
            rows.reverse()
        else:
            cursor.execute(
                """
                SELECT t, o, h, l, c, v, a, pc, ma5, ma10, ma20, ma60
                FROM daily_kline
                WHERE dm = %s
                ORDER BY t ASC
                """,
                (dm,),
            )
            rows = cursor.fetchall()
        return [normalize_kline(row) for row in rows]
    finally:
        if own and conn is not None:
            cursor.close()
            conn.close()


def _bulk_replace_flags(cursor, dm: str, klines: list[dict[str, Any]],
                        flags: list[dict[str, int]], today_only: bool = False) -> int:
    """today_only=True 时只更新今日因子，保留历史数据。"""
    if not today_only:
        cursor.execute("DELETE FROM factor_flag WHERE dm = %s", (dm,))
        rows: list[tuple] = []
        for bar, flag_map in zip(klines, flags):
            day = bar["t"]
            if day is None:
                continue
            for name, value in flag_map.items():
                if value:
                    rows.append((dm, day, name, 1))
        if not rows:
            return 0
        sql_prefix = "INSERT INTO factor_flag (dm, t, factor, flag) VALUES "
        written = 0
        for offset in range(0, len(rows), INSERT_CHUNK):
            chunk = rows[offset : offset + INSERT_CHUNK]
            placeholders = ",".join(["(%s,%s,%s,%s)"] * len(chunk))
            flat: list[Any] = []
            for item in chunk:
                flat.extend(item)
            cursor.execute(sql_prefix + placeholders, flat)
            written += len(chunk)
        return written
    else:
        # today_only：只更新最后一根K线（今日）的因子
        if not klines or not flags:
            return 0
        bar = klines[-1]
        flag_map = flags[-1]
        today = bar["t"]
        if today is None:
            return 0
        # 先删今日
        cursor.execute(
            "DELETE FROM factor_flag WHERE dm = %s AND t = %s",
            (dm, today),
        )
        rows = []
        for name, value in flag_map.items():
            if value:
                rows.append((dm, today, name, 1))
        if not rows:
            return 0
        sql_prefix = "INSERT INTO factor_flag (dm, t, factor, flag) VALUES "
        written = 0
        for offset in range(0, len(rows), INSERT_CHUNK):
            chunk = rows[offset : offset + INSERT_CHUNK]
            placeholders = ",".join(["(%s,%s,%s,%s)"] * len(chunk))
            flat: list[Any] = []
            for item in chunk:
                flat.extend(item)
            cursor.execute(sql_prefix + placeholders, flat)
            written += len(chunk)
        return written


def run(limit: int | None = None, today_only: bool = False) -> dict[str, int]:
    """计算全市场（或 --limit）因子并写入 factor_flag。
       today_only=True 时只加载最近65天数据，大幅加速日更。
    """
    ensure_tables()
    RECENT_DAYS = 65  # 刚好覆盖最长均线MA60 + 足够历史判断形态
    codes = load_stock_codes(limit)
    counts = {name: 0 for name in FACTOR_NAMES}
    if not codes:
        print("[factor] stock_basic 为空，请先完成数据同步")
        return counts

    print(f"[factor] 开始计算 股票={len(codes)} 因子={len(FACTOR_NAMES)}")
    written_rows = 0
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            for index, dm in enumerate(codes, start=1):
                klines = load_klines(dm, cursor, recent_days=RECENT_DAYS if today_only else None)
                if not klines:
                    if index % 50 == 0 or index == len(codes):
                        print(f"[factor] 进度 {index}/{len(codes)} 已写入={written_rows}")
                    continue
                flags = compute_factor_flags(klines)
                for flag_map in flags:
                    for name, value in flag_map.items():
                        if value:
                            counts[name] += 1
                written_rows += _bulk_replace_flags(cursor, dm, klines, flags, today_only=today_only)
                if index % 20 == 0:
                    conn.commit()
                if index % 50 == 0 or index == len(codes):
                    print(f"[factor] 进度 {index}/{len(codes)} 已写入={written_rows}")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    print(f"[factor] 完成，命中行={written_rows}")
    for name in FACTOR_NAMES:
        mark = "用户" if name in USER_FACTORS else "补充"
        print(f"[factor] {name} ({mark}) 命中={counts[name]}")
    missing_user = [n for n in USER_FACTORS if counts[n] <= 0]
    if missing_user:
        print(f"[factor] 警告：用户指定因子无命中 {missing_user}")
    return counts


def combo_key(factors: tuple[str, ...] | list[str]) -> str:
    return "+".join(sorted(factors))


def parse_combo(combo: str) -> tuple[str, ...]:
    parts = [p.strip() for p in str(combo or "").split("+") if p.strip()]
    return tuple(sorted(parts))


def is_st_name(mc: Optional[str]) -> bool:
    return "ST" in str(mc or "").upper()


def is_tradable_exchange(jys: Optional[str]) -> bool:
    return str(jys or "").strip().upper() in {"SZ", "SH"}
