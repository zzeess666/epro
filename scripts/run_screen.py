#!/usr/bin/env python3
"""CLI：用当前最优组合筛当日股票，输出 TOP5-10（含止损）。"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.screen.dynamic_screener import DEFAULT_TOP, TOP_MAX, TOP_MIN, run


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="动态选股：最优组合筛当日股票")
    parser.add_argument(
        "--date",
        default=None,
        help="交易日 YYYY-MM-DD，默认 factor_flag 最新日",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=DEFAULT_TOP,
        help=f"输出只数，{TOP_MIN}-{TOP_MAX}，默认 {DEFAULT_TOP}",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    day: date | None = None
    if args.date:
        try:
            day = date.fromisoformat(str(args.date).strip()[:10])
        except ValueError:
            print(f"[screen] 非法日期 {args.date}，需 YYYY-MM-DD")
            return 2
    if args.top < TOP_MIN or args.top > TOP_MAX:
        print(f"[screen] --top 需在 {TOP_MIN}-{TOP_MAX} 之间")
        return 2
    rows = run(day, top_n=args.top)
    print(f"[screen] 完成，推荐数={len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
