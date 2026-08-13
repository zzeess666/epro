#!/usr/bin/env python3
"""CLI：生成当日 TOP3 推荐，写入 recommend_result。"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.recommend.recommend_engine import run


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="风控过滤 + 统一评分，输出当日 TOP3 推荐")
    parser.add_argument(
        "--date",
        default=None,
        help="交易日 YYYY-MM-DD，默认最新交易日",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    day: date | None = None
    if args.date:
        try:
            day = date.fromisoformat(str(args.date).strip()[:10])
        except ValueError:
            print(f"[recommend] 非法日期 {args.date}，需 YYYY-MM-DD")
            return 2
    rows = run(day)
    print(f"[recommend] 完成，推荐数={len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
