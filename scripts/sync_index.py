#!/usr/bin/env python3
"""CLI：同步上证/深成/科创50/创业板指日K（2015至今）并计算 MA20。"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.index.index_sync import run


def main() -> int:
    run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
