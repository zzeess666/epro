#!/usr/bin/env python3
"""CLI：计算因子库并写入 factor_flag。
   --today  仅计算今日（快速日更），默认全量
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.factor.factor_library import run


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="计算因子库并写入 factor_flag")
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="仅计算前 N 只股票（调试用）；默认全市场",
    )
    parser.add_argument(
        "--today",
        action="store_true",
        help="仅计算今日因子（快速日更），只加载最近65天数据",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.limit is not None and args.limit <= 0:
        print("[factor] --limit 必须为正整数")
        return 1
    counts = run(args.limit, today_only=args.today)
    total = sum(counts.values())
    print(f"[factor] 完成，共写入 {total} 条因子记录")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
