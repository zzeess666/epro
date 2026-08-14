"""读取 .env，暴露数据库与麦蕊相关配置。"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent

load_dotenv(PROJECT_ROOT / ".env")

# 硬上限：放开到全市场（约5200只）；测试可用 SYNC_STOCK_LIMIT 环境变量限制
_MAX_SYNC_STOCK_LIMIT = 6000


def _int_env(name: str, default: str) -> int:
    raw = os.getenv(name, default).strip()
    try:
        return int(raw)
    except ValueError:
        return int(default)


def _parse_api_keys(raw: str) -> list[str]:
    keys: list[str] = []
    seen: set[str] = set()
    for part in raw.replace(";", ",").split(","):
        key = part.strip()
        if not key or key in seen:
            continue
        seen.add(key)
        keys.append(key)
    return keys


def _sync_stock_limit() -> int:
    value = _int_env("SYNC_STOCK_LIMIT", "100")
    if value <= 0:
        return _MAX_SYNC_STOCK_LIMIT
    return min(value, _MAX_SYNC_STOCK_LIMIT)


DB_HOST = os.getenv("DB_HOST", "127.0.0.1").strip() or "127.0.0.1"
DB_PORT = _int_env("DB_PORT", "3306")
DB_NAME = os.getenv("DB_NAME", "epro").strip() or "epro"
DB_USER = os.getenv("DB_USER", "epro").strip() or "epro"
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_CHARSET = os.getenv("DB_CHARSET", "utf8mb4").strip() or "utf8mb4"

MAIRUI_API_KEYS = _parse_api_keys(os.getenv("MAIRUI_API_KEYS", ""))
MAIRUI_API_BASE = (
    os.getenv("MAIRUI_API_BASE", "https://api.mairuiapi.com").strip().rstrip("/")
    or "https://api.mairuiapi.com"
)

SYNC_STOCK_LIMIT = _sync_stock_limit()
