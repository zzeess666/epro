"""风控过滤：四铁律 + 市值/估值，任一不满足即一票否决。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from config.config import SYNC_STOCK_LIMIT
from src.api.mairui_client import MairuiApiError, MairuiClient
from src.db.connection import get_connection

MAX_LOSS_PCT = 0.04
MIN_LTSZ_YI = 20.0
MAX_LTSZ_YI = 500.0
MAX_PE = 50.0
MAX_PB = 5.0
YI_YUAN = 100_000_000.0
_LOSS_EPS = 1e-9


@dataclass
class FilterStats:
    input_count: int = 0
    passed: int = 0
    reject_loss: int = 0
    reject_st: int = 0
    reject_mcap: int = 0
    reject_pe: int = 0
    reject_pb: int = 0
    reject_other: int = 0
    reasons: list[str] = field(default_factory=list)

    def add_reject(self, dm: str, strategy: str, reason: str) -> None:
        self.reasons.append(f"{dm}/{strategy}: {reason}")
        if reason.startswith("max_loss"):
            self.reject_loss += 1
        elif reason.startswith("st"):
            self.reject_st += 1
        elif reason.startswith("mcap"):
            self.reject_mcap += 1
        elif reason.startswith("pe"):
            self.reject_pe += 1
        elif reason.startswith("pb"):
            self.reject_pb += 1
        else:
            self.reject_other += 1


def filter_signals(
    signals: list[dict[str, Any]],
    client: Optional[MairuiClient] = None,
) -> tuple[list[dict[str, Any]], FilterStats]:
    """对候选信号做风控过滤；市值/PE/PB 优先用实时行情并回写 stock_basic。"""
    stats = FilterStats(input_count=len(signals))
    if not signals:
        return [], stats

    dms = _unique_dms(signals)
    basics = _load_stock_basic(dms)
    quotes = _enrich_fundamentals(dms, client)

    passed: list[dict[str, Any]] = []
    for sig in signals:
        dm = str(sig.get("dm") or "").strip()
        strategy = str(sig.get("strategy") or "")
        reason = _veto_reason(sig, basics.get(dm, {}), quotes.get(dm))
        if reason is None:
            merged = dict(sig)
            quote = quotes.get(dm) or {}
            basic = basics.get(dm, {})
            merged["mc"] = quote.get("mc") or basic.get("mc")
            merged["ltsz"] = quote.get("ltsz", basic.get("ltsz"))
            merged["pe"] = quote.get("pe", basic.get("pe"))
            merged["pb"] = quote.get("pb", basic.get("pb"))
            passed.append(merged)
            continue
        stats.add_reject(dm or "?", strategy or "?", reason)

    stats.passed = len(passed)
    print(
        f"[risk] 入选前={stats.input_count} 通过={stats.passed} "
        f"止损超标={stats.reject_loss} ST={stats.reject_st} "
        f"市值={stats.reject_mcap} PE={stats.reject_pe} PB={stats.reject_pb} "
        f"其他={stats.reject_other}"
    )
    return passed, stats


def _veto_reason(
    sig: dict[str, Any],
    basic: dict[str, Any],
    quote: Optional[dict[str, Any]],
) -> Optional[str]:
    entry = _to_float(sig.get("entry_price"))
    stop = _to_float(sig.get("stop_loss"))
    if entry is None or stop is None or entry <= 0:
        return "max_loss:买入/止损缺失"
    loss = (entry - stop) / entry
    if loss > MAX_LOSS_PCT + _LOSS_EPS:
        return f"max_loss:{loss * 100:.2f}%>4%"

    mc = (quote or {}).get("mc") or basic.get("mc") or ""
    if not str(mc).strip():
        return "st:名称为空"
    if _is_st_or_delist(str(mc)):
        return f"st:{mc}"

    ltsz = _first_float((quote or {}).get("ltsz"), basic.get("ltsz"))
    if ltsz is None or ltsz <= 0:
        return "mcap:市值缺失"
    yi = ltsz / YI_YUAN
    if yi < MIN_LTSZ_YI or yi > MAX_LTSZ_YI:
        return f"mcap:{yi:.2f}亿不在{MIN_LTSZ_YI:.0f}-{MAX_LTSZ_YI:.0f}"

    pe = _first_float((quote or {}).get("pe"), basic.get("pe"))
    if pe is None:
        return "pe:空"
    if pe <= 0:
        return f"pe:非正{pe}"
    if pe >= MAX_PE:
        return f"pe:{pe}>=50"

    pb = _first_float((quote or {}).get("pb"), basic.get("pb"))
    if pb is None:
        return "pb:空"
    if pb <= 0:
        return f"pb:非正{pb}"
    if pb >= MAX_PB:
        return f"pb:{pb}>=5"
    return None


def _is_st_or_delist(mc: str) -> bool:
    name = mc.strip()
    if "退" in name:
        return True
    upper = name.upper()
    return "ST" in upper


def _unique_dms(signals: list[dict[str, Any]]) -> list[str]:
    seen: set[str] = set()
    dms: list[str] = []
    for sig in signals:
        dm = str(sig.get("dm") or "").strip()
        if not dm or dm in seen:
            continue
        seen.add(dm)
        dms.append(dm)
        if len(dms) >= SYNC_STOCK_LIMIT:
            break
    return dms


def _load_stock_basic(dms: list[str]) -> dict[str, dict[str, Any]]:
    if not dms:
        return {}
    placeholders = ",".join(["%s"] * len(dms))
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT dm, mc, ltsz, zsz, pe, pb
                FROM stock_basic
                WHERE dm IN ({placeholders})
                """,
                tuple(dms),
            )
            rows = cursor.fetchall()
    finally:
        conn.close()
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        dm = str(row["dm"])
        out[dm] = {
            "dm": dm,
            "mc": row.get("mc"),
            "ltsz": _to_float(row.get("ltsz")),
            "zsz": _to_float(row.get("zsz")),
            "pe": _to_float(row.get("pe")),
            "pb": _to_float(row.get("pb")),
        }
    return out


def _enrich_fundamentals(
    dms: list[str],
    client: Optional[MairuiClient],
) -> dict[str, dict[str, Any]]:
    """对候选股拉实时行情，回写 ltsz/pe/pb（及 zsz）。失败则跳过该股。"""
    if not dms:
        return {}
    api = client or MairuiClient()
    quotes: dict[str, dict[str, Any]] = {}
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    updates: list[tuple] = []

    for i, dm in enumerate(dms, start=1):
        try:
            raw = api.get_realtime_quote(dm)
        except (MairuiApiError, ValueError, RuntimeError) as exc:
            print(f"[risk] 行情失败 {dm}: {exc}")
            continue
        parsed = _parse_quote(raw)
        if parsed is None:
            print(f"[risk] 行情字段无效 {dm}")
            continue
        quotes[dm] = parsed
        updates.append(
            (parsed["ltsz"], parsed["zsz"], parsed["pe"], parsed["pb"], now, dm)
        )
        if i % 10 == 0 or i == len(dms):
            print(f"[risk] 行情进度 {i}/{len(dms)}")

    if updates:
        conn = get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.executemany(
                    """
                    UPDATE stock_basic
                    SET ltsz = COALESCE(%s, ltsz),
                        zsz = COALESCE(%s, zsz),
                        pe = COALESCE(%s, pe),
                        pb = COALESCE(%s, pb),
                        updated_at = %s
                    WHERE dm = %s
                    """,
                    updates,
                )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        print(f"[risk] 回写 stock_basic 基本面={len(updates)}")
    return quotes


def _parse_quote(raw: dict[str, Any]) -> Optional[dict[str, Any]]:
    pe = _to_float(raw.get("pe"))
    pb = _to_float(raw.get("sjl"))
    if pb is None:
        pb = _to_float(raw.get("pb"))
    lt = _to_float(raw.get("lt"))
    sz = _to_float(raw.get("sz"))
    ltsz = _mcap_to_yuan(lt) if lt is not None and lt > 0 else None
    zsz = _mcap_to_yuan(sz) if sz is not None and sz > 0 else None
    return {
        "pe": pe,
        "pb": pb,
        "ltsz": ltsz,
        "zsz": zsz,
        "mc": raw.get("mc") or raw.get("name"),
    }


def _mcap_to_yuan(value: float) -> float:
    """麦蕊 lt/sz 统一成元：亿元(<1万) / 万元(<1亿) / 元。"""
    if value >= YI_YUAN:
        return value
    if value >= 10_000:
        return value * 10_000.0
    return value * YI_YUAN


def _to_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _first_float(*values: Any) -> Optional[float]:
    for value in values:
        parsed = _to_float(value)
        if parsed is not None:
            return parsed
    return None
