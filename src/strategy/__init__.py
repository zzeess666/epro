"""策略层：A 二次突破 / B 缩量回踩 / C 综合评分。"""

from __future__ import annotations

from src.strategy.base_strategy import (
    STRATEGY_CODES,
    BaseStrategy,
    Signal,
    ensure_tables,
    load_klines,
    load_stock_codes,
    run,
)
from src.strategy.strategy_a import StrategyA
from src.strategy.strategy_b import StrategyB
from src.strategy.strategy_c import StrategyC

STRATEGY_CLASSES: dict[str, type[BaseStrategy]] = {
    "A": StrategyA,
    "B": StrategyB,
    "C": StrategyC,
}


def get_strategy(name: str) -> BaseStrategy:
    key = (name or "").strip().upper()
    if key not in STRATEGY_CLASSES:
        raise ValueError(f"未知策略: {name}，可选 {', '.join(STRATEGY_CODES)}")
    return STRATEGY_CLASSES[key]()


def iter_strategies(name: str | None = None) -> list[BaseStrategy]:
    key = (name or "ALL").strip().upper()
    if key in ("", "ALL"):
        return [cls() for cls in STRATEGY_CLASSES.values()]
    return [get_strategy(key)]


__all__ = [
    "STRATEGY_CODES",
    "BaseStrategy",
    "Signal",
    "StrategyA",
    "StrategyB",
    "StrategyC",
    "get_strategy",
    "iter_strategies",
    "ensure_tables",
    "load_klines",
    "load_stock_codes",
    "run",
]
