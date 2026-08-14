#!/usr/bin/env python3
"""CLI：同步日K。默认日常增量（最近30交易日）；--init 初始化全历史。"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.sync.daily_kline_sync import run


def main() -> int:
    init = "--init" in sys.argv
    run(init=init)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
