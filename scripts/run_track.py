#!/usr/bin/env python3
"""CLI：生成/更新跟踪清单，盘中检查价格，尾盘输出达标提醒。"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.track.track_service import run


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="次日跟踪：生成清单 + 盘中检查 + 尾盘提醒")
    parser.add_argument(
        "--date",
        default=None,
        help="跟踪日期 YYYY-MM-DD，默认按最新推荐的次日/当日",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    day: date | None = None
    if args.date:
        try:
            day = date.fromisoformat(str(args.date).strip()[:10])
        except ValueError:
            print(f"[track] 非法日期 {args.date}，需 YYYY-MM-DD")
            return 2
    result = run(day)
    n = len(result.get("updated") or [])
    print(f"[track] 完成，盘中更新={n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
