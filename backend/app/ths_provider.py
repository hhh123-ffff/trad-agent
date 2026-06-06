from __future__ import annotations

import os
from datetime import date, datetime, timedelta
from typing import Any

import requests

from .history_provider import HistoryDataUnavailable, normalize_symbol
from .market_provider import CN_TZ
from .models import AnnouncementItem, DailyBar, SourceRef, StockUniverseItem


class TonghuashunDataUnavailable(HistoryDataUnavailable):
    pass


def ths_delayed_source() -> SourceRef:
    return SourceRef(
        id="src-ths-quantapi-delayed",
        name="同花顺 iFinD QuantAPI 延迟历史行情",
        url="https://quantapi.51ifind.com/",
        as_of=datetime.now(CN_TZ),
        license="licensed-or-terminal-entitled-source",
        freshness="盘后/延迟行情；用于个人复盘、统计和研究筛选，具体延迟与权限以账号开通范围为准",
    )


def ths_market_source() -> SourceRef:
    return SourceRef(
        id="src-ths-quantapi-market",
        name="同花顺 iFinD QuantAPI 行情",
        url="https://quantapi.51ifind.com/",
        as_of=datetime.now(CN_TZ),
        license="licensed-or-terminal-entitled-source",
        freshness="同花顺/iFinD 授权行情；可用于盘后复盘、统计和研究筛选，具体延迟与权限以账号开通范围为准",
    )


def ths_announcement_source() -> SourceRef:
    return SourceRef(
        id="src-ths-quantapi-announcement",
        name="同花顺 iFinD QuantAPI 公告",
        url="https://quantapi.51ifind.com/",
        as_of=datetime.now(CN_TZ),
        license="licensed-or-terminal-entitled-source",
        freshness="同花顺/iFinD 公告检索接口；仅保存标题、时间、证券代码和链接",
    )


class TonghuashunQuantApiClient:
    """Small HTTP client for iFinD QuantAPI endpoints used by post-market research."""

    def __init__(
        self,
        *,
        refresh_token: str | None = None,
        access_token: str | None = None,
        base_url: str | None = None,
        timeout_seconds: float | None = None,
    ):
        self.refresh_token = refresh_token or os.getenv("THS_REFRESH_TOKEN", "")
        self.access_token = access_token or os.getenv("THS_ACCESS_TOKEN", "")
        self.base_url = (base_url or os.getenv("THS_QUANTAPI_BASE_URL", "https://quantapi.51ifind.com/api/v1")).rstrip("/")
        self.timeout_seconds = timeout_seconds or float(os.getenv("THS_TIMEOUT_SECONDS", "15"))

    def history_bars(self, symbol: str, *, days: int, period: str = "D", adjust: str = "qfq") -> list[DailyBar]:
        end = date.today()
        lookback_days = max(days * 14, 365) if period.upper().startswith("W") else max(days * 2, 180)
        start = end - timedelta(days=lookback_days)
        indicators = os.getenv("THS_HISTORY_INDICATORS", "open,high,low,close,volume,amount,changeRatio,turnoverRatio")
        functionpara = {
            "Fill": "Blank",
            "Interval": period,
            "CPS": _ths_adjust(adjust),
        }
        payload = self._post(
            "/cmd_history_quotation",
            {
                "codes": _ths_symbol(symbol),
                "indicators": indicators,
                "startdate": start.strftime("%Y-%m-%d"),
                "enddate": end.strftime("%Y-%m-%d"),
                "functionpara": functionpara,
            },
        )
        rows = _rows_from_history_payload(payload, _ths_symbol(symbol))
        bars = _bars_from_rows(symbol=normalize_symbol(symbol), rows=rows, adjust=adjust)
        if not bars:
            raise TonghuashunDataUnavailable(f"{symbol} 同花顺历史行情为空。")
        return bars[-days:]

    def real_time_quotes(self, symbols: list[str], indicators: str | None = None) -> dict[str, dict[str, Any]]:
        normalized = [_ths_symbol(symbol) for symbol in symbols if symbol]
        if not normalized:
            return {}
        payload = self._post(
            "/real_time_quotation",
            {
                "codes": ",".join(normalized),
                "indicators": indicators
                or os.getenv("THS_REALTIME_INDICATORS", "latest,changeRatio,amount,volumeRatio"),
            },
        )
        quotes: dict[str, dict[str, Any]] = {}
        for table in _extract_tables(payload):
            symbol = _ths_symbol(str(table.get("thscode") or table.get("code") or table.get("symbol") or ""))
            if not symbol:
                continue
            row = _single_row_from_table(table)
            if row:
                row["symbol"] = symbol
                quotes[symbol] = row
        return quotes

    def stock_universe(self, searchstring: str | None = None) -> list[StockUniverseItem]:
        payload = self._post(
            "/smart_stock_picking",
            {
                "searchstring": searchstring or os.getenv("THS_UNIVERSE_SEARCHSTRING", "全部A股"),
                "searchtype": "stock",
            },
        )
        items: dict[str, StockUniverseItem] = {}
        for row in _rows_from_any_payload(payload):
            item = _stock_item_from_row(row)
            if item is not None:
                items[item.symbol] = item
        if not items:
            raise TonghuashunDataUnavailable("同花顺智能选股未返回 A 股股票池。")
        return list(items.values())

    def announcements(
        self,
        symbols: list[str] | None = None,
        *,
        begin_date: date | None = None,
        end_date: date | None = None,
        report_type: str | None = None,
    ) -> list[AnnouncementItem]:
        end = end_date or datetime.now(CN_TZ).date()
        begin = begin_date or end
        normalized = [_ths_symbol(symbol) for symbol in symbols or [] if symbol]
        if not normalized:
            return []
        payload = self._post(
            "/report_query",
            {
                "codes": ",".join(normalized),
                "functionpara": {"reportType": report_type or os.getenv("THS_ANNOUNCEMENT_REPORT_TYPE", "901")},
                "beginrDate": begin.strftime("%Y-%m-%d"),
                "endrDate": end.strftime("%Y-%m-%d"),
                "outputpara": os.getenv(
                    "THS_ANNOUNCEMENT_OUTPUTPARA",
                    "reportDate:Y,thscode:Y,secName:Y,ctime:Y,reportTitle:Y,pdfURL:Y,seq:Y",
                ),
            },
        )
        items: list[AnnouncementItem] = []
        for row in _rows_from_any_payload(payload):
            item = _announcement_from_row(row, fallback_date=end)
            if item is not None:
                items.append(item)
        return items[:500]

    def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        token = self._ensure_access_token()
        try:
            response = requests.post(
                url=f"{self.base_url}{path}",
                json=body,
                headers={"Content-Type": "application/json", "access_token": token, "ifindlang": "cn"},
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            raise TonghuashunDataUnavailable(f"同花顺 QuantAPI 请求失败：{exc}") from exc
        _raise_for_ths_error(payload)
        return payload

    def _ensure_access_token(self) -> str:
        if self.access_token:
            return self.access_token
        if not self.refresh_token:
            raise TonghuashunDataUnavailable(
                "THS_ACCESS_TOKEN or THS_REFRESH_TOKEN is required when MARKETLENS_HISTORY_PROVIDER=ths_delayed."
            )
        try:
            response = requests.post(
                url=f"{self.base_url}/get_access_token",
                headers={"Content-Type": "application/json", "refresh_token": self.refresh_token},
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            raise TonghuashunDataUnavailable(f"同花顺 access_token 获取失败：{exc}") from exc
        _raise_for_ths_error(payload)
        token = str((payload.get("data") or {}).get("access_token") or "").strip()
        if not token:
            raise TonghuashunDataUnavailable("同花顺 access_token 响应为空。")
        self.access_token = token
        return token


def _raise_for_ths_error(payload: dict[str, Any]) -> None:
    error_code = payload.get("errorcode", payload.get("code", 0))
    try:
        normalized = int(error_code)
    except (TypeError, ValueError):
        normalized = 0 if str(error_code).strip() in {"", "0"} else -1
    if normalized != 0:
        message = payload.get("errmsg") or payload.get("msg") or payload.get("message") or "unknown error"
        raise TonghuashunDataUnavailable(f"同花顺 QuantAPI 返回错误 {normalized}: {message}")


def _ths_symbol(symbol: str) -> str:
    if not str(symbol or "").strip():
        return ""
    return normalize_symbol(symbol).upper()


def _ths_adjust(adjust: str) -> str:
    normalized = (adjust or "").lower()
    if normalized in {"", "none", "raw", "bfq"}:
        return "1"
    if normalized in {"qfq", "forward", "forward1"}:
        return "2"
    if normalized in {"hfq", "backward", "backward1"}:
        return "3"
    return adjust


def _rows_from_history_payload(payload: dict[str, Any], symbol: str) -> list[dict[str, Any]]:
    tables = _extract_tables(payload)
    for table in tables:
        table_symbol = str(table.get("thscode") or table.get("code") or table.get("symbol") or "").upper()
        if table_symbol and table_symbol != symbol.upper():
            continue
        rows = _rows_from_table(table)
        if rows:
            return rows
    return _rows_from_table(payload)


def _rows_from_any_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    tables = _extract_tables(payload)
    if not tables:
        return _rows_from_table(payload)
    for table in tables:
        rows.extend(_rows_from_table(table))
    return rows


def _extract_tables(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw_tables = payload.get("tables")
    if raw_tables is None and isinstance(payload.get("data"), dict):
        raw_tables = payload["data"].get("tables")
    if isinstance(raw_tables, dict):
        return [raw_tables]
    if isinstance(raw_tables, list):
        return [table for table in raw_tables if isinstance(table, dict)]
    return []


def _rows_from_table(table: dict[str, Any]) -> list[dict[str, Any]]:
    raw_table = table.get("table")
    if isinstance(raw_table, list):
        return [row for row in raw_table if isinstance(row, dict)]
    if not isinstance(raw_table, dict):
        raw_table = table

    columns = {str(key): value for key, value in raw_table.items() if key not in {"table", "thscode", "code", "symbol"}}
    times = table.get("time") or columns.get("time") or columns.get("date") or columns.get("trade_date") or []
    if not isinstance(times, list):
        times = [times]
    max_len = max([len(value) for value in columns.values() if isinstance(value, list)] + [len(times)])
    rows: list[dict[str, Any]] = []
    metadata = {key: table[key] for key in ("thscode", "code", "symbol") if key in table}
    for index in range(max_len):
        row: dict[str, Any] = dict(metadata)
        if index < len(times):
            row["time"] = times[index]
        for key, value in columns.items():
            if isinstance(value, list):
                row[key] = value[index] if index < len(value) else None
            else:
                row[key] = value
        rows.append(row)
    return rows


def _single_row_from_table(table: dict[str, Any]) -> dict[str, Any]:
    rows = _rows_from_table(table)
    if rows:
        return rows[-1]
    raw_table = table.get("table")
    if isinstance(raw_table, dict):
        return {key: _last(value) for key, value in raw_table.items()}
    return {key: _last(value) for key, value in table.items() if key not in {"table", "thscode"}}


def _bars_from_rows(symbol: str, rows: list[dict[str, Any]], adjust: str) -> list[DailyBar]:
    bars: list[DailyBar] = []
    previous_close: float | None = None
    for row in rows:
        trade_date = _parse_date(_pick(row, "time", "date", "trade_date", "datetime"))
        if trade_date is None:
            continue
        close = _number(_pick(row, "close", "ths_close_price_stock"))
        if close <= 0:
            continue
        change_pct = _number(_pick(row, "changeRatio", "change_pct", "pct_chg", "涨跌幅"), default=None)
        if change_pct is None and previous_close:
            change_pct = (close / previous_close - 1) * 100
        bars.append(
            DailyBar(
                symbol=symbol,
                trade_date=trade_date,
                open=_number(_pick(row, "open", "ths_open_price_stock")),
                high=_number(_pick(row, "high", "ths_high_price_stock")),
                low=_number(_pick(row, "low", "ths_low_stock")),
                close=close,
                volume=_number(_pick(row, "volume", "vol", "ths_vol_stock")),
                amount=_number(_pick(row, "amount", "ths_trans_amount_stock")),
                change_pct=float(change_pct or 0),
                turnover_rate=_number(_pick(row, "turnoverRatio", "turnover_rate", "ths_turnover_ratio_stock")),
                adjust=adjust,
            )
        )
        previous_close = close
    return sorted(bars, key=lambda bar: bar.trade_date)


def _pick(row: dict[str, Any], *keys: str) -> Any:
    lowered = {str(key).lower(): value for key, value in row.items()}
    for key in keys:
        if key in row and row[key] not in (None, ""):
            return row[key]
        value = lowered.get(key.lower())
        if value not in (None, ""):
            return value
    return None


def _last(value: Any) -> Any:
    if isinstance(value, list):
        return value[-1] if value else None
    return value


def _stock_item_from_row(row: dict[str, Any]) -> StockUniverseItem | None:
    raw_symbol = _pick(row, "thscode", "code", "symbol", "证券代码", "股票代码")
    raw_name = _pick(row, "secName", "name", "股票简称", "证券简称", "简称")
    if not raw_symbol or not raw_name:
        return None
    name = str(raw_name).strip()
    return StockUniverseItem(
        symbol=_ths_symbol(str(raw_symbol)),
        name=name,
        is_st=("ST" in name.upper()) or ("退" in name),
        listed_days=_listed_days(_pick(row, "上市日期", "A股上市日期", "listingDate", "listDate", "ipoDate")),
        market="A股",
    )


def _listed_days(value: Any) -> int:
    listing_date = _parse_date(value)
    return max((date.today() - listing_date).days, 0) if listing_date else 0


def _announcement_from_row(row: dict[str, Any], fallback_date: date) -> AnnouncementItem | None:
    symbol = _pick(row, "thscode", "code", "symbol")
    title = _pick(row, "reportTitle", "title", "公告标题")
    if not symbol or not title:
        return None
    published = _parse_datetime(
        _pick(row, "ctime", "reportDate", "datetime", "published_at"),
        fallback=datetime.combine(fallback_date, datetime.min.time(), CN_TZ).replace(hour=16),
    )
    normalized_symbol = _ths_symbol(str(symbol))
    sec_name = str(_pick(row, "secName", "name") or "").strip()
    title_text = str(title).strip()
    return AnnouncementItem(
        id=_stable_id("ths-announcement", normalized_symbol, title_text, published.isoformat(), str(_pick(row, "seq") or "")),
        symbol=normalized_symbol,
        title=title_text[:300],
        summary=(f"{sec_name}：{title_text}" if sec_name else title_text)[:800],
        published_at=published,
        source_url=str(_pick(row, "pdfURL", "url", "source_url") or "").strip(),
        source_name="同花顺 iFinD 公告",
        event_type="announcement",
        importance=_announcement_importance(title_text),
        provider="ths-quantapi-info",
        source_id="src-ths-quantapi-announcement",
        license_note="同花顺/iFinD QuantAPI 公告接口，仅保存标题摘要和链接",
    )


def _number(value: Any, default: float | None = 0) -> float | None:
    try:
        if value in (None, "", "-", "--"):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _parse_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raw = str(value or "").strip()
    if not raw:
        return None
    for fmt, length in (("%Y-%m-%d", 10), ("%Y%m%d", 8), ("%Y-%m-%d %H:%M:%S", 19)):
        try:
            return datetime.strptime(raw[:length], fmt).date()
        except ValueError:
            continue
    return None


def _parse_datetime(value: Any, fallback: datetime) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=CN_TZ)
    parsed_date = _parse_date(value)
    if parsed_date is not None:
        raw = str(value or "")
        for fmt, length in (("%Y-%m-%d %H:%M:%S", 19), ("%Y%m%d%H%M%S", 14)):
            try:
                parsed = datetime.strptime(raw[:length], fmt)
                return parsed.replace(tzinfo=CN_TZ)
            except ValueError:
                continue
        return datetime.combine(parsed_date, datetime.min.time(), CN_TZ).replace(hour=16)
    return fallback


def _stable_id(*parts: str) -> str:
    import hashlib

    digest = hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:16]
    return "-".join([parts[0], digest])


def _announcement_importance(title: str) -> str:
    high_terms = ("重大", "停牌", "复牌", "重组", "问询函", "监管", "处罚", "风险提示", "退市", "业绩预告")
    return "high" if any(term in title for term in high_terms) else "medium"
