from __future__ import annotations

import os
import socket
from datetime import date, datetime, timedelta
from typing import Any

from .market_provider import CN_TZ
from .models import DailyBar, SourceRef, StockUniverseItem, ThemeMembership

HISTORY_TIMEOUT_SECONDS = float(os.getenv("MARKETLENS_HISTORY_TIMEOUT_SECONDS", "15"))
socket.setdefaulttimeout(HISTORY_TIMEOUT_SECONDS)


def _install_requests_default_timeout(timeout_seconds: float) -> None:
    try:
        import requests
    except Exception:
        return
    original_request = requests.sessions.Session.request
    if getattr(original_request, "_marketlens_timeout_patch", False):
        return

    def request_with_default_timeout(self: Any, method: str, url: str, **kwargs: Any) -> Any:
        if kwargs.get("timeout") is None:
            kwargs["timeout"] = timeout_seconds
        return original_request(self, method, url, **kwargs)

    request_with_default_timeout._marketlens_timeout_patch = True  # type: ignore[attr-defined]
    requests.sessions.Session.request = request_with_default_timeout


_install_requests_default_timeout(HISTORY_TIMEOUT_SECONDS)


class HistoryDataUnavailable(RuntimeError):
    pass


def akshare_source() -> SourceRef:
    return SourceRef(
        id="src-akshare-dev",
        name="AKShare 研发历史行情",
        url="https://akshare.akfamily.xyz/",
        as_of=datetime.now(CN_TZ),
        license="public-dev-source",
        freshness="历史日线/周线和题材数据；商业化前应替换为授权数据源",
    )


def _ak() -> Any:
    try:
        import akshare as ak
    except Exception as exc:
        raise HistoryDataUnavailable("未安装 AKShare，无法拉取历史行情。") from exc
    return ak


def _pd() -> Any:
    try:
        import pandas as pd
    except Exception as exc:
        raise HistoryDataUnavailable("未安装 pandas，无法处理历史行情。") from exc
    return pd


def normalize_symbol(code: str) -> str:
    raw = str(code).strip().upper().replace(".", "").replace("SH", "").replace("SZ", "").replace("BJ", "")
    if raw.startswith(("5", "6", "9")):
        return f"{raw}.SH"
    if raw.startswith(("4", "8")):
        return f"{raw}.BJ"
    return f"{raw}.SZ"


def symbol_code(symbol: str) -> str:
    return symbol.split(".")[0]


def _listed_days(value: Any) -> int:
    if not value:
        return 999
    try:
        if isinstance(value, datetime):
            listing_date = value.date()
        elif isinstance(value, date):
            listing_date = value
        else:
            raw = str(value).strip()
            if not raw:
                return 999
            listing_date = datetime.strptime(raw[:10], "%Y-%m-%d").date()
    except Exception:
        return 999
    return max((date.today() - listing_date).days, 0)


def _stock_item_from_row(row: dict[str, Any]) -> StockUniverseItem | None:
    code = str(row.get("code") or row.get("证券代码") or row.get("A股代码") or "").strip()
    name = str(row.get("name") or row.get("证券简称") or row.get("A股简称") or "").strip()
    if not code or not name:
        return None
    return StockUniverseItem(
        symbol=normalize_symbol(code),
        name=name,
        is_st=("ST" in name.upper()) or ("退" in name),
        listed_days=_listed_days(row.get("上市日期") or row.get("A股上市日期")),
        market="A股",
    )


def _items_from_frame(frame: Any) -> list[StockUniverseItem]:
    items: dict[str, StockUniverseItem] = {}
    if frame is None or frame.empty:
        return []
    for row in frame.to_dict("records"):
        item = _stock_item_from_row(row)
        if item is not None:
            items[item.symbol] = item
    return list(items.values())


def fetch_stock_universe() -> list[StockUniverseItem]:
    ak = _ak()
    errors: list[str] = []
    try:
        frame = ak.stock_info_a_code_name()
    except Exception as exc:
        errors.append(f"stock_info_a_code_name: {exc}")
    else:
        items = _items_from_frame(frame)
        if items:
            return items

    fallback_items: dict[str, StockUniverseItem] = {}
    fallback_calls = (
        ("上交所主板", lambda: ak.stock_info_sh_name_code(symbol="主板A股")),
        ("上交所科创板", lambda: ak.stock_info_sh_name_code(symbol="科创板")),
        ("深交所A股", lambda: ak.stock_info_sz_name_code(symbol="A股列表")),
    )
    for label, fetcher in fallback_calls:
        try:
            for item in _items_from_frame(fetcher()):
                fallback_items[item.symbol] = item
        except Exception as exc:
            errors.append(f"{label}: {exc}")
    if fallback_items:
        return list(fallback_items.values())
    raise HistoryDataUnavailable(f"AKShare 股票列表不可用：{'; '.join(errors)}")


def fetch_daily_bars(symbol: str, days: int = 250, adjust: str = "qfq") -> list[DailyBar]:
    return _fetch_hist_bars(symbol=symbol, period="daily", days=days, adjust=adjust)


def fetch_weekly_bars(symbol: str, weeks: int = 80, adjust: str = "qfq") -> list[DailyBar]:
    return _fetch_hist_bars(symbol=symbol, period="weekly", days=weeks * 8, adjust=adjust)[-weeks:]


def _fetch_hist_bars(symbol: str, period: str, days: int, adjust: str) -> list[DailyBar]:
    ak = _ak()
    pd = _pd()
    end = date.today()
    start = end - timedelta(days=max(days * 2, 180))
    try:
        frame = ak.stock_zh_a_hist(
            symbol=symbol_code(symbol),
            period=period,
            start_date=start.strftime("%Y%m%d"),
            end_date=end.strftime("%Y%m%d"),
            adjust=adjust,
        )
    except Exception as exc:
        try:
            return _fetch_hist_bars_sina(symbol=symbol, period=period, days=days, adjust=adjust)
        except Exception as fallback_exc:
            raise HistoryDataUnavailable(f"{symbol} 历史行情不可用：东财接口失败：{exc}；新浪备选失败：{fallback_exc}") from fallback_exc
    if frame is None or frame.empty:
        try:
            return _fetch_hist_bars_sina(symbol=symbol, period=period, days=days, adjust=adjust)
        except Exception as fallback_exc:
            raise HistoryDataUnavailable(f"{symbol} 历史行情为空；新浪备选失败：{fallback_exc}") from fallback_exc
    frame = frame.rename(
        columns={
            "日期": "date",
            "开盘": "open",
            "收盘": "close",
            "最高": "high",
            "最低": "low",
            "成交量": "volume",
            "成交额": "amount",
            "涨跌幅": "change_pct",
            "换手率": "turnover_rate",
        }
    )
    frame["date"] = pd.to_datetime(frame["date"]).dt.date
    frame = frame.sort_values("date").tail(days)
    bars: list[DailyBar] = []
    for row in frame.to_dict("records"):
        bars.append(
            DailyBar(
                symbol=symbol,
                trade_date=row.get("date") or row.get("trade_date"),
                open=float(row.get("open") or 0),
                high=float(row.get("high") or 0),
                low=float(row.get("low") or 0),
                close=float(row.get("close") or 0),
                volume=float(row.get("volume") or 0),
                amount=float(row.get("amount") or 0),
                change_pct=float(row.get("change_pct") or 0),
                turnover_rate=float(row.get("turnover_rate") or 0),
                adjust=adjust,
            )
    )
    return bars


def _sina_symbol(symbol: str) -> str:
    code = symbol_code(symbol)
    suffix = symbol.split(".")[-1].upper()
    if suffix == "SH":
        return f"sh{code}"
    if suffix == "SZ":
        return f"sz{code}"
    if suffix == "BJ":
        return f"bj{code}"
    return code


def _fetch_hist_bars_sina(symbol: str, period: str, days: int, adjust: str) -> list[DailyBar]:
    ak = _ak()
    pd = _pd()
    end = date.today()
    start = end - timedelta(days=max(days * 2, 180))
    frame = ak.stock_zh_a_daily(
        symbol=_sina_symbol(symbol),
        start_date=start.strftime("%Y%m%d"),
        end_date=end.strftime("%Y%m%d"),
        adjust=adjust,
    )
    if frame is None or frame.empty:
        raise HistoryDataUnavailable("新浪日线为空。")
    frame = frame.copy()
    frame["date"] = pd.to_datetime(frame["date"]).dt.date
    frame = frame.sort_values("date")
    frame["change_pct"] = frame["close"].pct_change().fillna(0) * 100
    frame["turnover_rate"] = frame.get("turnover", 0) * 100
    if period == "weekly":
        return _weekly_bars_from_daily_frame(symbol=symbol, frame=frame, adjust=adjust)
    return _daily_bars_from_frame(symbol=symbol, frame=frame.tail(days), adjust=adjust)


def _daily_bars_from_frame(symbol: str, frame: Any, adjust: str) -> list[DailyBar]:
    bars: list[DailyBar] = []
    for row in frame.to_dict("records"):
        bars.append(
            DailyBar(
                symbol=symbol,
                trade_date=row.get("date") or row.get("trade_date"),
                open=float(row.get("open") or 0),
                high=float(row.get("high") or 0),
                low=float(row.get("low") or 0),
                close=float(row.get("close") or 0),
                volume=float(row.get("volume") or 0),
                amount=float(row.get("amount") or 0),
                change_pct=float(row.get("change_pct") or 0),
                turnover_rate=float(row.get("turnover_rate") or 0),
                adjust=adjust,
            )
        )
    return bars


def _weekly_bars_from_daily_frame(symbol: str, frame: Any, adjust: str) -> list[DailyBar]:
    pd = _pd()
    weekly = frame.copy()
    weekly["date_ts"] = pd.to_datetime(weekly["date"])
    weekly["week"] = weekly["date_ts"].dt.to_period("W-FRI")
    grouped = weekly.groupby("week", sort=True)
    result = grouped.agg(
        trade_date=("date", "last"),
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
        amount=("amount", "sum"),
        turnover_rate=("turnover_rate", "sum"),
    ).reset_index(drop=True)
    result["change_pct"] = result["close"].pct_change().fillna(0) * 100
    return _daily_bars_from_frame(symbol=symbol, frame=result, adjust=adjust)


def fetch_theme_memberships(symbols: list[str], max_themes: int = 24) -> list[ThemeMembership]:
    if not symbols:
        return []
    ak = _ak()
    wanted = {symbol_code(symbol) for symbol in symbols}
    memberships: list[ThemeMembership] = []
    try:
        concepts = ak.stock_board_concept_name_em()
    except Exception:
        concepts = None
    if concepts is not None and not concepts.empty:
        theme_names = [str(row.get("板块名称") or row.get("name") or "") for row in concepts.to_dict("records")[:max_themes]]
        for theme_name in [name for name in theme_names if name]:
            try:
                cons = ak.stock_board_concept_cons_em(symbol=theme_name)
            except Exception:
                continue
            for row in cons.to_dict("records"):
                code = str(row.get("代码") or row.get("code") or "")
                if code in wanted:
                    memberships.append(ThemeMembership(symbol=normalize_symbol(code), theme_name=theme_name, theme_type="concept"))
    return memberships
