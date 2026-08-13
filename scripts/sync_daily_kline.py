#!/usr/bin/env python3
"""CLI：同步日K（≤100 只，近 120 个交易日）。"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.sync.daily_kline_sync import run


def main() -> int:
    run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
