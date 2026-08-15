"""组合挖掘：枚举 2-3 指标组合，按 4 周期回测训练/测试胜率。

信号日 = 组合内全部因子当日均为 1（只标记不买）；
买入日 = 信号日后 5 个交易日内第一个回踩日（收盘买入）；收益模拟只用买入日之后的 K 线。
大盘过滤：板块对应指数收盘 > MA20 才统计该信号。
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from itertools import combinations
from typing import Any, Optional

from src.db.connection import get_connection
from src.factor.factor_library import (
    FACTOR_NAMES,
    combo_key,
    ensure_tables as ensure_factor_tables,
    is_st_name,
    is_tradable_exchange,
    load_klines,
)
from src.strategy.base_strategy import to_date

TRAIN_RATIO = 0.80
PULLBACK_WINDOW = 10

# 板块 → 对应大盘指数
INDEX_STAR = "000688.SH"       # 科创板 688
INDEX_CHINEXT = "399006.SZ"    # 创业板 300/301
INDEX_SH = "000001.SH"         # 沪市主板 600/601/603/605
INDEX_SZ = "399001.SZ"         # 深市主板及其他


@dataclass(frozen=True)
class PeriodSpec:
    period: str
    hold_days: int
    stop_pct: float


# 超短 3 天 2%；短 5 天 3-4%；中短 20 天 5-6%；中 60 天 8%
PERIODS: tuple[PeriodSpec, ...] = (
    PeriodSpec("超短", 3, 0.02),
    PeriodSpec("短", 5, 0.035),
    PeriodSpec("中短", 20, 0.055),
    PeriodSpec("中", 60, 0.08),
)


@dataclass
class ComboPeriodStats:
    combo: str
    period: str
    hold_days: int
    stop_pct: float
    train_wins: int = 0
    train_n: int = 0
    test_wins: int = 0
    test_n: int = 0

    @property
    def train_win_rate(self) -> float:
        if self.train_n <= 0:
            return 0.0
        return 100.0 * self.train_wins / self.train_n

    @property
    def test_win_rate(self) -> float:
        if self.test_n <= 0:
            return 0.0
        return 100.0 * self.test_wins / self.test_n

    def add(self, ret: float, is_train: bool) -> None:
        win = 1 if ret > 0 else 0
        if is_train:
            self.train_n += 1
            self.train_wins += win
        else:
            self.test_n += 1
            self.test_wins += win


def index_code_for_dm(dm: str) -> str:
    """按股票代码前缀映射板块对应指数。"""
    code = "".join(ch for ch in str(dm).strip() if ch.isdigit())
    prefix3 = code[:3]
    if prefix3 == "688":
        return INDEX_STAR
    if prefix3 in ("300", "301"):
        return INDEX_CHINEXT
    if prefix3 in ("600", "601", "603", "605"):
        return INDEX_SH
    return INDEX_SZ


def load_index_bull_map() -> dict[str, dict[date, bool]]:
    """预加载 index_kline：code → {日: 收盘>MA20}。缺 ma20/收盘视为 False。"""
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT code, t, c, ma20
                FROM index_kline
                ORDER BY code, t
                """
            )
            rows = cursor.fetchall()
    finally:
        conn.close()
    out: dict[str, dict[date, bool]] = defaultdict(dict)
    for row in rows:
        code = str(row.get("code") or "").strip().upper()
        day = to_date(row.get("t"))
        if not code or day is None:
            continue
        close = row.get("c")
        ma20 = row.get("ma20")
        if close is None or ma20 is None:
            out[code][day] = False
            continue
        out[code][day] = float(close) > float(ma20)
    return dict(out)


def is_market_bull(
    dm: str,
    day: date,
    bull_map: dict[str, dict[date, bool]] | None = None,
) -> bool:
    """板块对应指数当日收盘 > MA20 则为多头，允许统计；否则空仓。

    无指数数据或 ma20 不足时返回 False（不用未来数据补全）。
    """
    index_code = index_code_for_dm(dm)
    if bull_map is not None:
        return bool(bull_map.get(index_code, {}).get(day, False))

    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT c, ma20
                FROM index_kline
                WHERE code = %s AND t = %s
                LIMIT 1
                """,
                (index_code, day),
            )
            row = cursor.fetchone()
    finally:
        conn.close()
    if not row:
        return False
    close = row.get("c")
    ma20 = row.get("ma20")
    if close is None or ma20 is None:
        return False
    return float(close) > float(ma20)


def enumerate_combos(factor_names: tuple[str, ...] | list[str] | None = None) -> list[tuple[str, ...]]:
    names = tuple(factor_names) if factor_names is not None else FACTOR_NAMES
    names = tuple(sorted(names))
    out: list[tuple[str, ...]] = []
    for size in (2, 3):
        out.extend(combinations(names, size))
    return out


def load_trade_dates() -> list[date]:
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT DISTINCT t FROM daily_kline ORDER BY t ASC")
            days: list[date] = []
            for row in cursor.fetchall():
                day = to_date(row["t"])
                if day is not None:
                    days.append(day)
            return days
    finally:
        conn.close()


def split_train_test(dates: list[date], ratio: float = TRAIN_RATIO) -> tuple[set[date], set[date]]:
    """前 80% 交易日训练，后 20% 测试。按日历切分，不按股票。"""
    if not dates:
        return set(), set()
    ordered = sorted(dates)
    cut = int(len(ordered) * ratio)
    if cut <= 0:
        cut = max(len(ordered) - 1, 0)
    if cut >= len(ordered):
        cut = max(len(ordered) - 1, 1)
    return set(ordered[:cut]), set(ordered[cut:])


def load_tradable_codes(limit: int | None = None) -> list[str]:
    """挖掘/选股同一宇宙：沪深、非 ST、非京市。"""
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT dm, mc, jys FROM stock_basic ORDER BY dm")
            rows = cursor.fetchall()
    finally:
        conn.close()
    codes: list[str] = []
    for row in rows:
        if not is_tradable_exchange(row.get("jys")):
            continue
        if is_st_name(row.get("mc")):
            continue
        codes.append(row["dm"])
        if limit is not None and int(limit) > 0 and len(codes) >= int(limit):
            break
    return codes


def _load_flags(cursor, dm: str) -> dict[date, set[str]]:
    cursor.execute(
        """
        SELECT t, factor
        FROM factor_flag
        WHERE dm = %s AND flag = 1
        """,
        (dm,),
    )
    out: dict[date, set[str]] = defaultdict(set)
    for row in cursor.fetchall():
        day = to_date(row["t"])
        factor = str(row["factor"] or "").strip()
        if day is None or not factor:
            continue
        out[day].add(factor)
    return dict(out)


def _find_pullback_entry(
    klines: list[dict[str, Any]],
    signal_index: int,
) -> Optional[tuple[int, float]]:
    """信号日后最多 PULLBACK_WINDOW 个交易日内找第一个回踩日。

    回踩条件（全部满足）：最低价≤MA10、收盘价>MA20、成交量≤信号日成交量。
    返回 (买入下标, 买入价=回踩日收盘)；无回踩则 None。
    """
    if signal_index < 0 or signal_index >= len(klines):
        return None
    signal_vol = klines[signal_index].get("v")
    signal_close = klines[signal_index].get("c")
    if signal_vol is None or signal_close is None:
        return None
    signal_vol_f = float(signal_vol)
    signal_close_f = float(signal_close)

    n = len(klines)
    last = min(signal_index + PULLBACK_WINDOW, n - 1)
    for i in range(signal_index + 1, last + 1):
        bar = klines[i]
        low = bar.get("l")
        close = bar.get("c")
        ma10 = bar.get("ma10")
        ma20 = bar.get("ma20")
        vol = bar.get("v")
        if low is None or close is None or ma10 is None or ma20 is None or vol is None:
            continue
        close_f = float(close)
        if close_f <= 0:
            continue
        if close_f < signal_close_f and close_f > float(ma20) and float(vol) <= signal_vol_f:
            return i, close_f
    return None


def _simulate_periods(
    klines: list[dict[str, Any]],
    entry_index: int,
    entry_price: float,
) -> dict[str, Optional[float]]:
    """从回踩买入日起持有，一次扫描算出 4 个周期收益率；未来 K 线不足则该周期为 None。"""
    results: dict[str, Optional[float]] = {}
    if entry_price <= 0:
        return {p.period: None for p in PERIODS}

    n = len(klines)
    for spec in PERIODS:
        exit_index = entry_index + spec.hold_days
        if exit_index >= n:
            results[spec.period] = None
            continue
        stop = entry_price * (1.0 - spec.stop_pct)
        stopped = False
        for j in range(entry_index + 1, exit_index + 1):
            low = klines[j]["l"]
            if low is not None and low <= stop:
                results[spec.period] = (stop - entry_price) / entry_price * 100.0
                stopped = True
                break
        if stopped:
            continue
        exit_close = klines[exit_index]["c"]
        if exit_close is None:
            results[spec.period] = None
        else:
            results[spec.period] = (exit_close - entry_price) / entry_price * 100.0
    return results


def _empty_stats(combos: list[tuple[str, ...]]) -> dict[tuple[str, str], ComboPeriodStats]:
    stats: dict[tuple[str, str], ComboPeriodStats] = {}
    for combo in combos:
        key = combo_key(combo)
        for spec in PERIODS:
            stats[(key, spec.period)] = ComboPeriodStats(
                combo=key,
                period=spec.period,
                hold_days=spec.hold_days,
                stop_pct=spec.stop_pct,
            )
    return stats


def mine(limit: int | None = None) -> list[ComboPeriodStats]:
    """对每个 2-3 因子组合分周期回测，返回训练/测试样本与胜率。"""
    ensure_factor_tables()
    combos = enumerate_combos()
    stats = _empty_stats(combos)
    dates = load_trade_dates()
    train_dates, test_dates = split_train_test(dates)
    codes = load_tradable_codes(limit)
    bull_map = load_index_bull_map()

    print(
        f"[miner] 组合数={len(combos)} 周期={len(PERIODS)} "
        f"股票={len(codes)} 交易日={len(dates)} "
        f"训练日={len(train_dates)} 测试日={len(test_dates)} "
        f"指数日={sum(len(v) for v in bull_map.values())}"
    )
    if not codes:
        print("[miner] 无可用股票（需沪深非 ST）")
        return list(stats.values())
    if not train_dates or not test_dates:
        print("[miner] 交易日不足以做 80/20 切分")
        return list(stats.values())
    if not bull_map:
        print("[miner] index_kline 为空，请先运行 sync_index.py；大盘过滤将全部空仓")

    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            for index, dm in enumerate(codes, start=1):
                flags_by_date = _load_flags(cursor, dm)
                if not flags_by_date:
                    if index % 50 == 0 or index == len(codes):
                        print(f"[miner] 进度 {index}/{len(codes)}")
                    continue
                klines = load_klines(dm, cursor)
                date_to_index = {
                    bar["t"]: i for i, bar in enumerate(klines) if bar["t"] is not None
                }
                for day, hit_factors in flags_by_date.items():
                    if len(hit_factors) < 2:
                        continue
                    if day not in train_dates and day not in test_dates:
                        continue
                    if not is_market_bull(dm, day, bull_map):
                        continue
                    signal_index = date_to_index.get(day)
                    if signal_index is None:
                        continue
                    pullback = _find_pullback_entry(klines, signal_index)
                    if pullback is None:
                        continue
                    entry_index, entry_price = pullback
                    period_rets = _simulate_periods(klines, entry_index, entry_price)
                    if all(v is None for v in period_rets.values()):
                        continue
                    is_train = day in train_dates
                    names = sorted(hit_factors)
                    known = [name for name in names if name in FACTOR_NAMES]
                    day_combos = []
                    if len(known) >= 2:
                        day_combos.extend(combinations(known, 2))
                    if len(known) >= 3:
                        day_combos.extend(combinations(known, 3))
                    for combo in day_combos:
                        key = combo_key(combo)
                        for spec in PERIODS:
                            ret = period_rets.get(spec.period)
                            if ret is None:
                                continue
                            row = stats.get((key, spec.period))
                            if row is None:
                                continue
                            row.add(ret, is_train)
                if index % 50 == 0 or index == len(codes):
                    print(f"[miner] 进度 {index}/{len(codes)}")
    finally:
        conn.close()

    return list(stats.values())
