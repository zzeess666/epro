"""策略 A：二次突破（首次 30 日新高 → 缩量回调 → 再次突破）。"""

from __future__ import annotations

from typing import Any, Optional

from src.strategy.base_strategy import BaseStrategy, Signal, breakout_strength

LOOKBACK_BROW = 5
MIN_STRENGTH = 30
PULLBACK_FLOOR = 0.95
VOLUME_SHRINK = 1.1


class StrategyA(BaseStrategy):
    name = "A"
    min_bars = 31

    def evaluate(self, dm: str, klines: list[dict[str, Any]], index: int) -> Optional[Signal]:
        if index < self.min_bars - 1:
            return None

        today = klines[index]
        close = today["c"]
        volume = today["v"]
        if today["t"] is None or close is None or volume is None:
            return None

        today_strength = breakout_strength(klines, index)
        if today_strength < MIN_STRENGTH:
            return None

        window_start = max(0, index - LOOKBACK_BROW)
        for j in range(window_start, index):
            brow = klines[j]
            brow_high = brow["h"]
            brow_close = brow["c"]
            brow_low = brow["l"]
            if None in (brow_high, brow_close, brow_low):
                continue
            if close <= brow_high:
                continue
            brow_strength = breakout_strength(klines, j)
            if brow_strength < MIN_STRENGTH:
                continue
            if not _pullback_ok(klines, j, index, brow_high, brow_close, volume):
                continue

            stop_loss = max(brow_low, close * 0.96)
            return Signal(
                dm=dm,
                t=today["t"],
                strategy=self.name,
                entry_price=close,
                stop_loss=stop_loss,
                score=None,
                detail={
                    "brow_date": str(brow["t"]),
                    "brow_high": brow_high,
                    "brow_close": brow_close,
                    "brow_low": brow_low,
                    "stop_cap": close * 0.96,
                    "today_strength": today_strength,
                    "brow_strength": brow_strength,
                    "pullback_days": index - j - 1,
                },
            )
        return None


def _pullback_ok(
    klines: list[dict[str, Any]],
    brow_index: int,
    today_index: int,
    brow_high: float,
    brow_close: float,
    today_volume: float,
) -> bool:
    """bRow 到今日之间的回调质量：不破高、缩量不破低、收盘站上 ma5。"""
    low_bound = PULLBACK_FLOOR * brow_close
    vol_cap = VOLUME_SHRINK * today_volume
    for k in range(brow_index + 1, today_index):
        mid = klines[k]
        mid_high = mid["h"]
        mid_close = mid["c"]
        mid_vol = mid["v"]
        mid_ma5 = mid["ma5"]
        if None in (mid_high, mid_close, mid_vol, mid_ma5):
            return False
        if mid_high >= brow_high:
            return False
        if not (low_bound <= mid_close <= brow_close):
            return False
        if mid_vol > vol_cap:
            return False
        if mid_close <= mid_ma5:
            return False
    return True
