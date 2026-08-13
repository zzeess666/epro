#!/usr/bin/env python3
"""CLI：同步股票列表（≤100 只）。"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.sync.stock_list_sync import run


def main() -> int:
    run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
