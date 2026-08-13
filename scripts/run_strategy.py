#!/usr/bin/env python3
"""CLI：跑策略生成信号。默认 A/B/C 全部，可 --strategy A 单跑。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.strategy import STRATEGY_CODES, run


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="生成策略信号并写入 strategy_signal")
    parser.add_argument(
        "--strategy",
        default="ALL",
        help="A/B/C，默认全部",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    key = (args.strategy or "ALL").strip().upper()
    if key not in ("ALL", *STRATEGY_CODES):
        print(f"[strategy] 非法策略 {args.strategy}，可选 ALL/{'/'.join(STRATEGY_CODES)}")
        return 2
    counts = run(None if key == "ALL" else key)
    total = sum(counts.values())
    print(f"[strategy] 完成，合计信号={total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
