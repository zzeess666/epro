"""策略 B：缩量回踩（多头排列 + 回踩均线 + 缩量止跌）。"""

from __future__ import annotations

from typing import Any, Optional

from src.strategy.base_strategy import BaseStrategy, Signal, avg_volume

NEAR_MA10_PCT = 0.02
NEAR_MA20_PCT = 0.03
VOLUME_SHRINK = 0.50


class StrategyB(BaseStrategy):
    name = "B"
    min_bars = 20

    def evaluate(self, dm: str, klines: list[dict[str, Any]], index: int) -> Optional[Signal]:
        if index < self.min_bars - 1 or index < 5:
            return None

        today = klines[index]
        open_p = today["o"]
        high = today["h"]
        low = today["l"]
        close = today["c"]
        volume = today["v"]
        ma5 = today["ma5"]
        ma10 = today["ma10"]
        ma20 = today["ma20"]
        if today["t"] is None or None in (open_p, high, low, close, volume, ma5, ma10, ma20):
            return None
        if ma10 <= 0 or ma20 <= 0:
            return None
        if not (ma5 > ma10 > ma20):
            return None

        near_ma10 = abs(close - ma10) / ma10 <= NEAR_MA10_PCT
        near_ma20 = abs(close - ma20) / ma20 <= NEAR_MA20_PCT
        if not (near_ma10 or near_ma20):
            return None

        prev_avg_vol = avg_volume(klines, index - 5, index)
        if prev_avg_vol is None or prev_avg_vol <= 0:
            return None
        if volume > VOLUME_SHRINK * prev_avg_vol:
            return None

        is_yang = close >= open_p
        has_lower_shadow = low < close
        if not (is_yang or has_lower_shadow):
            return None

        return Signal(
            dm=dm,
            t=today["t"],
            strategy=self.name,
            entry_price=close,
            stop_loss=max(ma20, close * 0.96),
            score=None,
            detail={
                "ma5": ma5,
                "ma10": ma10,
                "ma20": ma20,
                "near": "ma10" if near_ma10 else "ma20",
                "vol_vs_5d": round(volume / prev_avg_vol, 4),
                "stop_signal": "yang" if is_yang else "lower_shadow",
            },
        )
