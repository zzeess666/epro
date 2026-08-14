"""麦蕊 Token 轮询器：轮询取 key，单 key 每日不超过 500 次。"""

from __future__ import annotations

import fcntl
import json
from datetime import date
from pathlib import Path
from typing import Optional

from config.config import MAIRUI_API_KEYS, PROJECT_ROOT


class ApiKeyExhaustedError(RuntimeError):
    """当日全部 Token 均已达到调用上限。"""


class ApiKeyRotator:
    DAILY_LIMIT = 5000

    def __init__(
        self,
        keys: Optional[list[str]] = None,
        state_file: Optional[Path] = None,
        daily_limit: int = DAILY_LIMIT,
    ) -> None:
        raw_keys = keys if keys is not None else MAIRUI_API_KEYS
        self.keys = [k.strip() for k in raw_keys if k and k.strip()]
        if not self.keys:
            raise RuntimeError("MAIRUI_API_KEYS 未配置或为空")
        self.daily_limit = daily_limit
        log_dir = PROJECT_ROOT / "storage" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        self.state_file = Path(state_file) if state_file else log_dir / "mairui_api_key.rotate"

    def next(self) -> str:
        """轮询返回下一个未超限的 token，并记一次调用。"""
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.state_file, "a+", encoding="utf-8") as fp:
            fcntl.flock(fp, fcntl.LOCK_EX)
            try:
                fp.seek(0)
                raw = fp.read().strip()
                state = self._load_state(raw)
                key = self._pick_key(state)
                state["counts"][key] = int(state["counts"].get(key, 0)) + 1
                state["cursor"] = (self.keys.index(key) + 1) % len(self.keys)
                fp.seek(0)
                fp.truncate()
                json.dump(state, fp, ensure_ascii=False)
                fp.flush()
                return key
            finally:
                fcntl.flock(fp, fcntl.LOCK_UN)

    def remaining(self, key: str) -> int:
        counts = self._snapshot()["counts"]
        used = int(counts.get(key, 0))
        return max(self.daily_limit - used, 0)

    def count(self) -> int:
        return len(self.keys)

    def _snapshot(self) -> dict:
        if not self.state_file.exists():
            return self._empty_state()
        with open(self.state_file, "r", encoding="utf-8") as fp:
            fcntl.flock(fp, fcntl.LOCK_SH)
            try:
                return self._load_state(fp.read().strip())
            finally:
                fcntl.flock(fp, fcntl.LOCK_UN)

    def _pick_key(self, state: dict) -> str:
        n = len(self.keys)
        start = int(state.get("cursor", 0)) % n
        counts = state.setdefault("counts", {})
        for offset in range(n):
            key = self.keys[(start + offset) % n]
            used = int(counts.get(key, 0))
            if used < self.daily_limit:
                return key
        raise ApiKeyExhaustedError(
            f"全部 Token 当日调用已达上限 {self.daily_limit} 次，请次日再试"
        )

    def _load_state(self, raw: str) -> dict:
        today = date.today().isoformat()
        if not raw:
            return self._empty_state(today)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return self._empty_state(today)
        if not isinstance(data, dict) or data.get("date") != today:
            return self._empty_state(today)
        data.setdefault("cursor", 0)
        data.setdefault("counts", {})
        if not isinstance(data["counts"], dict):
            data["counts"] = {}
        return data

    def _empty_state(self, today: Optional[str] = None) -> dict:
        return {
            "date": today or date.today().isoformat(),
            "cursor": 0,
            "counts": {},
        }
