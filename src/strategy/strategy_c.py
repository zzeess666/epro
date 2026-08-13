"""策略 C：综合评分（M2 仅本地可算维度；估值/利润留 TODO）。"""

from __future__ import annotations

from typing import Any, Optional

from src.strategy.base_strategy import BaseStrategy, Signal, avg_volume

# TODO(M3+): 估值维度 25% — PE/PB，需财务/实时接口，M2 不调用
# TODO(M3+): 利润维度 25% — ROE/EPS，需财务接口，M2 不调用
TECH_WEIGHT = 0.50
FUND_WEIGHT = 0.50
HIT_SCORE = 60.0
UPPER_SHADOW_MAX = 0.50


class StrategyC(BaseStrategy):
    name = "C"
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
        if today["t"] is None or None in (open_p, high, low, close, volume):
            return None

        prev_close = klines[index - 5]["c"]
        prev_avg_vol = avg_volume(klines, index - 5, index)
        vol_ratio = (
            volume / prev_avg_vol if prev_avg_vol is not None and prev_avg_vol > 0 else None
        )
        ret5 = (
            (close - prev_close) / prev_close * 100.0
            if prev_close is not None and prev_close > 0
            else None
        )

        tech, tech_hits = _tech_score(close, ma5, ma10, ma20, ret5, vol_ratio)
        fund, fund_hits = _fund_score(open_p, high, low, close, vol_ratio)
        score = tech * TECH_WEIGHT + fund * FUND_WEIGHT
        if score < HIT_SCORE:
            return None

        stop_loss = _stop_loss(close, ma20)
        if stop_loss is None:
            return None

        return Signal(
            dm=dm,
            t=today["t"],
            strategy=self.name,
            entry_price=close,
            stop_loss=stop_loss,
            score=score,
            detail={
                "tech_score": tech,
                "fund_score": fund,
                "score": round(score, 2),
                "vol_ratio": None if vol_ratio is None else round(vol_ratio, 4),
                "ret5": None if ret5 is None else round(ret5, 2),
                "tech_hits": tech_hits,
                "fund_hits": fund_hits,
                "todo": [
                    "估值维度待补外部 PE/PB",
                    "利润维度待补 ROE/EPS",
                ],
            },
        )


def _tech_score(
    close: float,
    ma5: Optional[float],
    ma10: Optional[float],
    ma20: Optional[float],
    ret5: Optional[float],
    vol_ratio: Optional[float],
) -> tuple[int, list[str]]:
    """技术形态 0-100：多头+30，收>ma5+20，近5日涨幅3%-7%+30，量比>1.5+20。"""
    score = 0
    hits: list[str] = []
    if ma5 is not None and ma10 is not None and ma20 is not None and ma5 > ma10 > ma20:
        score += 30
        hits.append("ma5>ma10>ma20")
    if ma5 is not None and close > ma5:
        score += 20
        hits.append("close>ma5")
    if ret5 is not None and 3.0 <= ret5 <= 7.0:
        score += 30
        hits.append("ret5_3_7")
    if vol_ratio is not None and vol_ratio > 1.5:
        score += 20
        hits.append("vol_ratio>1.5")
    return score, hits


def _fund_score(
    open_p: float,
    high: float,
    low: float,
    close: float,
    vol_ratio: Optional[float],
) -> tuple[int, list[str]]:
    """资金活跃 0-100：放量1.2倍+40，量能温和放大+30，无长上影+30。"""
    score = 0
    hits: list[str] = []
    if vol_ratio is not None and vol_ratio > 1.2:
        score += 40
        hits.append("vol>1.2x5d")
    # 换手率暂无本地字段，用成交量相对 5 日均量 1.0~2.0 代理「温和放大」
    if vol_ratio is not None and 1.0 < vol_ratio <= 2.0:
        score += 30
        hits.append("mild_volume_expand")
    if _no_long_upper_shadow(open_p, high, low, close):
        score += 30
        hits.append("no_long_upper_shadow")
    return score, hits


def _no_long_upper_shadow(open_p: float, high: float, low: float, close: float) -> bool:
    rng = high - low
    if rng <= 0:
        return True
    upper = high - max(open_p, close)
    return (upper / rng) <= UPPER_SHADOW_MAX


def _stop_loss(close: float, ma20: Optional[float]) -> Optional[float]:
    if ma20 is not None and 0 < ma20 < close:
        return ma20
    if close > 0:
        return close * 0.96
    return None
