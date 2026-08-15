#!/usr/bin/env python3
"""CLI：组合挖掘 + 训练/测试双验证排行，写入 combo_rank。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.combo.win_rate_ranker import run


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="枚举 2-3 指标组合并按胜率排行")
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="仅挖掘前 N 只可交易股票（调试用）；默认全市场沪深非 ST",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.limit is not None and args.limit <= 0:
        print("[miner] --limit 必须为正整数")
        return 2
    rows = run(args.limit)
    print(f"[miner] 完成，达标组合={len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
