"""麦蕊 API 客户端：10 秒超时，失败重试 3 次。"""

from __future__ import annotations

import time
from typing import Any, Optional

import requests

from config.config import MAIRUI_API_BASE
from src.api.api_key_rotator import ApiKeyRotator


class MairuiApiError(RuntimeError):
    """麦蕊接口请求失败。"""


class MairuiClient:
    TIMEOUT_SECONDS = 10
    MAX_RETRIES = 3
    RETRY_SLEEP_SECONDS = 1

    def __init__(
        self,
        rotator: Optional[ApiKeyRotator] = None,
        base_url: Optional[str] = None,
    ) -> None:
        self.rotator = rotator or ApiKeyRotator()
        self.base_url = (base_url or MAIRUI_API_BASE).rstrip("/") + "/"

    def get_stock_list(self) -> list[dict[str, Any]]:
        licence = self.rotator.next()
        data = self._get(f"hslt/list/{licence}")
        return self._as_list(data)

    def get_realtime_quote(self, dm: str) -> dict[str, Any]:
        """实时行情 /hsrl/ssjy/{纯数字}/{licence}，返回单条行情。"""
        licence = self.rotator.next()
        code = "".join(ch for ch in str(dm).strip() if ch.isdigit())
        if not code:
            raise ValueError("股票代码为空")
        data = self._get(f"hsrl/ssjy/{code}/{licence}")
        return self._as_object(data)

    def get_daily_kline(
        self,
        code: str,
        jys: str,
        start: str,
        end: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        licence = self.rotator.next()
        symbol = self._api_symbol(code, jys)
        path = f"hsstock/history/{symbol}/d/n/{licence}"
        params = {
            "st": _compact_date(start),
            "et": _compact_date(end),
            "lt": int(limit),
        }
        data = self._get(path, params=params)
        return self._as_list(data)

    def get_index_history(
        self,
        code: str,
        start: str,
        end: str,
    ) -> list[dict[str, Any]]:
        """指数日K /hsindex/history/{code}/d/{licence}?st=&et=（无 n）。"""
        licence = self.rotator.next()
        symbol = str(code).strip().upper()
        if not symbol:
            raise ValueError("指数代码为空")
        path = f"hsindex/history/{symbol}/d/{licence}"
        params = {
            "st": _compact_date(start),
            "et": _compact_date(end),
        }
        data = self._get(path, params=params)
        return self._as_list(data)

    def _get(self, path: str, params: Optional[dict[str, Any]] = None) -> Any:
        url = self.base_url + path.lstrip("/")
        last_error: Optional[Exception] = None
        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                resp = requests.get(url, params=params, timeout=self.TIMEOUT_SECONDS)
                resp.raise_for_status()
                try:
                    return resp.json()
                except ValueError as exc:
                    raise MairuiApiError(
                        f"响应不是合法 JSON: {url} body={resp.text[:200]!r}"
                    ) from exc
            except (requests.RequestException, MairuiApiError) as exc:
                last_error = exc
                if attempt >= self.MAX_RETRIES:
                    break
                time.sleep(self.RETRY_SLEEP_SECONDS * attempt)
        raise MairuiApiError(f"请求失败（已重试 {self.MAX_RETRIES} 次）: {url}") from last_error

    @staticmethod
    def _as_list(data: Any) -> list[dict[str, Any]]:
        if isinstance(data, list):
            return [row for row in data if isinstance(row, dict)]
        raise MairuiApiError(f"接口返回格式异常: {type(data).__name__} {data!r}"[:300])

    @staticmethod
    def _as_object(data: Any) -> dict[str, Any]:
        if isinstance(data, dict):
            return data
        if isinstance(data, list):
            for row in data:
                if isinstance(row, dict):
                    return row
            raise MairuiApiError(f"接口返回空列表: {data!r}"[:300])
        raise MairuiApiError(f"接口返回格式异常: {type(data).__name__} {data!r}"[:300])

    @staticmethod
    def _api_symbol(code: str, jys: str) -> str:
        dm = str(code).strip()
        if "." in dm:
            dm, suffix = dm.split(".", 1)
            market = (jys or suffix).strip().upper()
        else:
            market = str(jys).strip().upper()
        if not dm:
            raise ValueError("股票代码为空")
        if not market:
            return dm
        return f"{dm}.{market}"


def _compact_date(value: str) -> str:
    text = str(value).strip().replace("-", "")
    if len(text) < 8:
        raise ValueError(f"日期格式无效: {value!r}")
    return text[:8]
