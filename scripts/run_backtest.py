#!/usr/bin/env python3
"""CLI：回溯计算胜率。默认全部策略，hold=5。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.backtest.backtest_engine import DEFAULT_HOLD_DAYS, run
from src.strategy import STRATEGY_CODES


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="回溯策略胜率并写入 backtest_result")
    parser.add_argument(
        "--strategy",
        default="ALL",
        help="A/B/C，默认全部",
    )
    parser.add_argument(
        "--hold-days",
        type=int,
        default=DEFAULT_HOLD_DAYS,
        help="模拟持有交易日数，默认 5",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    key = (args.strategy or "ALL").strip().upper()
    if key not in ("ALL", *STRATEGY_CODES):
        print(f"[backtest] 非法策略 {args.strategy}，可选 ALL/{'/'.join(STRATEGY_CODES)}")
        return 2
    if args.hold_days <= 0:
        print("[backtest] --hold-days 必须为正整数")
        return 2
    results = run(None if key == "ALL" else key, hold_days=args.hold_days)
    print(f"[backtest] 完成，策略数={len(results)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
