from __future__ import annotations

import hashlib
import os
from datetime import datetime, time
from typing import Any, Protocol

import requests

from .history_provider import HistoryDataUnavailable, akshare_source, fetch_daily_bars, fetch_stock_universe, fetch_theme_memberships, fetch_weekly_bars
from .market_provider import CN_TZ, live_market_bundle
from .market_provider import (
    build_market_events,
    fetch_quote_rows,
    live_source,
    sina_source,
)
from .models import (
    AnnouncementItem,
    DailyBar,
    DataSourceStatus,
    MarketEvent,
    MarketIndex,
    MarketTemperature,
    NewsItem,
    ProviderMeta,
    SectorSnapshot,
    SourceRef,
    StockUniverseItem,
    ThemeMembership,
    WatchlistStock,
)
from .ths_provider import (
    TonghuashunQuantApiClient,
    ths_announcement_source,
    ths_delayed_source,
    ths_market_source,
)


class MarketDataProvider(Protocol):
    name: str

    def current_bundle(
        self, watchlist: list[WatchlistStock]
    ) -> tuple[MarketTemperature, list[MarketIndex], list[SectorSnapshot], list[WatchlistStock], list[MarketEvent], ProviderMeta]:
        ...


class HistoryDataProvider(Protocol):
    name: str

    def stock_universe(self) -> list[StockUniverseItem]:
        ...

    def daily_bars(self, symbol: str, days: int = 250) -> list[DailyBar]:
        ...

    def weekly_bars(self, symbol: str, weeks: int = 80) -> list[DailyBar]:
        ...

    def theme_memberships(self, symbols: list[str]) -> list[ThemeMembership]:
        ...


class NewsAnnouncementProvider(Protocol):
    name: str

    def news(self, symbols: list[str] | None = None) -> list[NewsItem]:
        ...

    def announcements(self, symbols: list[str] | None = None) -> list[AnnouncementItem]:
        ...


class DevMarketDataProvider:
    name = "dev-eastmoney-sina"

    def current_bundle(
        self, watchlist: list[WatchlistStock]
    ) -> tuple[MarketTemperature, list[MarketIndex], list[SectorSnapshot], list[WatchlistStock], list[MarketEvent], ProviderMeta]:
        temperature, indexes, sectors, enriched_watchlist, events, source = live_market_bundle(watchlist)
        meta = ProviderMeta(
            provider=self.name,
            source_id=source.id,
            fetched_at=datetime.now(CN_TZ),
            license_note=source.license,
        )
        return temperature, indexes, sectors, enriched_watchlist, events, meta

    def quote_rows(self, symbols: list[str]) -> dict[str, dict[str, Any]]:
        return fetch_quote_rows(symbols)


class TonghuashunMarketDataProvider:
    name = "ths-quantapi-market"
    source_id = "src-ths-quantapi-market"

    def __init__(
        self,
        client: TonghuashunQuantApiClient | None = None,
        history_provider: HistoryDataProvider | None = None,
    ):
        self.client = client or TonghuashunQuantApiClient()
        self.history_provider = history_provider
        self.quote_batch_size = int(os.getenv("THS_QUOTE_BATCH_SIZE", "300"))
        self.max_universe_quotes = int(os.getenv("THS_MARKET_MAX_UNIVERSE_QUOTES", "6000"))

    def current_bundle(
        self, watchlist: list[WatchlistStock]
    ) -> tuple[MarketTemperature, list[MarketIndex], list[SectorSnapshot], list[WatchlistStock], list[MarketEvent], ProviderMeta]:
        universe = self._stock_universe()
        quote_symbols = [item.symbol for item in universe[: self.max_universe_quotes]]
        quotes = self.quote_rows(quote_symbols)
        if not quotes:
            raise RuntimeError("同花顺行情快照为空。")
        temperature = self._market_temperature(quotes)
        indexes = self._indexes()
        sectors = self._market_groups(universe, quotes)
        enriched_watchlist = self._enrich_watchlist(watchlist)
        events = build_market_events(temperature, sectors, enriched_watchlist, self.source_id)
        meta = ProviderMeta(
            provider=self.name,
            source_id=self.source_id,
            fetched_at=datetime.now(CN_TZ),
            license_note="同花顺/iFinD QuantAPI 授权或终端权益行情源",
        )
        return temperature, indexes, sectors, enriched_watchlist, events, meta

    def quote_rows(self, symbols: list[str]) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for batch in _chunks([symbol.upper() for symbol in symbols if symbol], self.quote_batch_size):
            result.update(self.client.real_time_quotes(batch))
        return result

    def _stock_universe(self) -> list[StockUniverseItem]:
        provider = self.history_provider or history_data_provider
        return provider.stock_universe()

    def _indexes(self) -> list[MarketIndex]:
        mapping = {
            "000001.SH": "上证指数",
            "399001.SZ": "深证成指",
            "399006.SZ": "创业板指",
        }
        quotes = self.quote_rows(list(mapping.keys()))
        indexes: list[MarketIndex] = []
        for symbol, name in mapping.items():
            row = quotes.get(symbol)
            if not row:
                continue
            indexes.append(
                MarketIndex(
                    symbol=symbol,
                    name=str(_pick(row, "name", "secName") or name),
                    value=_number(_pick(row, "latest", "close", "new")),
                    change_pct=_number(_pick(row, "changeRatio", "change_pct")),
                    turnover_billion=round(_number(_pick(row, "amount")) / 100_000_000, 2),
                    source_id=self.source_id,
                )
            )
        return indexes

    def _market_temperature(self, quotes: dict[str, dict[str, Any]]) -> MarketTemperature:
        valid = [row for row in quotes.values() if _number(_pick(row, "latest", "close", "new")) > 0]
        advancers = sum(1 for row in valid if _number(_pick(row, "changeRatio", "change_pct")) > 0)
        decliners = sum(1 for row in valid if _number(_pick(row, "changeRatio", "change_pct")) < 0)
        limit_up = sum(1 for row in valid if _number(_pick(row, "changeRatio", "change_pct")) >= 9.8)
        limit_down = sum(1 for row in valid if _number(_pick(row, "changeRatio", "change_pct")) <= -9.8)
        total_directional = max(advancers + decliners, 1)
        score = round(advancers / total_directional * 100)
        label = "偏活跃" if score >= 60 else "偏弱" if score <= 40 else "均衡"
        return MarketTemperature(
            score=max(0, min(100, score)),
            label=label,
            advancers=advancers,
            decliners=decliners,
            limit_up_count=limit_up,
            limit_down_count=limit_down,
            total_turnover_billion=round(sum(_number(_pick(row, "amount")) for row in valid) / 100_000_000, 2),
            updated_at=datetime.now(CN_TZ),
        )

    def _market_groups(self, universe: list[StockUniverseItem], quotes: dict[str, dict[str, Any]]) -> list[SectorSnapshot]:
        names = {item.symbol: item.name for item in universe}
        valid_rows = [
            {"symbol": symbol, "name": names.get(symbol, symbol), **row}
            for symbol, row in quotes.items()
            if _number(_pick(row, "latest", "close", "new")) > 0
        ]

        def symbols(sample: list[dict[str, Any]]) -> list[str]:
            return [str(row["symbol"]) for row in sample[:5]]

        def names_text(sample: list[dict[str, Any]]) -> str:
            return "、".join(str(row.get("name") or row.get("symbol")) for row in sample[:3])

        groups = [
            ("同花顺涨幅榜", sorted(valid_rows, key=lambda row: _number(_pick(row, "changeRatio", "change_pct")), reverse=True)[:10], "涨幅靠前"),
            ("同花顺跌幅榜", sorted(valid_rows, key=lambda row: _number(_pick(row, "changeRatio", "change_pct")))[:10], "跌幅靠前"),
            ("同花顺成交额榜", sorted(valid_rows, key=lambda row: _number(_pick(row, "amount")), reverse=True)[:10], "成交额靠前"),
            ("同花顺换手榜", sorted(valid_rows, key=lambda row: _number(_pick(row, "turnoverRatio", "turnover_rate")), reverse=True)[:10], "换手率靠前"),
        ]
        snapshots: list[SectorSnapshot] = []
        for name, sample, driver_prefix in groups:
            if not sample:
                continue
            snapshots.append(
                SectorSnapshot(
                    name=name,
                    change_pct=round(sum(_number(_pick(row, "changeRatio", "change_pct")) for row in sample) / len(sample), 2),
                    turnover_billion=round(sum(_number(_pick(row, "amount")) for row in sample) / 100_000_000, 2),
                    leading_symbols=symbols(sample),
                    driver=f"{driver_prefix}：{names_text(sample)}。该分组来自同花顺实时/延迟行情排序，不代表行业分类。",
                    confidence="medium",
                    source_id=self.source_id,
                )
            )
        return snapshots

    def _enrich_watchlist(self, items: list[WatchlistStock]) -> list[WatchlistStock]:
        if not items:
            return []
        quotes = self.quote_rows([item.symbol for item in items])
        enriched: list[WatchlistStock] = []
        for item in items:
            row = quotes.get(item.symbol)
            if not row:
                raise RuntimeError(f"未从同花顺获取到 {item.symbol} 行情。")
            latest = _number(_pick(row, "latest", "close", "new"))
            change_pct = _number(_pick(row, "changeRatio", "change_pct"))
            volume_ratio = _number(_pick(row, "volumeRatio", "vol_ratio"), 1)
            enriched.append(
                item.model_copy(
                    update={
                        "name": str(_pick(row, "name", "secName") or item.name),
                        "price": latest,
                        "change_pct": change_pct,
                        "volume_ratio": volume_ratio,
                        "latest_event": f"同花顺行情：{latest:.2f}，涨跌幅 {change_pct:+.2f}%。",
                        "source_id": self.source_id,
                    }
                )
            )
        return enriched


class DevHistoryDataProvider:
    name = "dev-akshare"
    source_ids = ["src-akshare-dev"]

    def stock_universe(self) -> list[StockUniverseItem]:
        return fetch_stock_universe()

    def daily_bars(self, symbol: str, days: int = 250) -> list[DailyBar]:
        return fetch_daily_bars(symbol, days=days)

    def weekly_bars(self, symbol: str, weeks: int = 80) -> list[DailyBar]:
        return fetch_weekly_bars(symbol, weeks=weeks)

    def theme_memberships(self, symbols: list[str]) -> list[ThemeMembership]:
        return fetch_theme_memberships(symbols)


class TonghuashunDelayedHistoryProvider:
    name = "ths-quantapi-delayed"
    source_ids = ["src-ths-quantapi-delayed", "src-akshare-dev"]

    def __init__(
        self,
        client: TonghuashunQuantApiClient | None = None,
        fallback: DevHistoryDataProvider | None = None,
        allow_bar_fallback: bool | None = None,
    ):
        self.client = client or TonghuashunQuantApiClient()
        self.fallback = fallback or DevHistoryDataProvider()
        self.allow_bar_fallback = (
            os.getenv("THS_HISTORY_FALLBACK_TO_AKSHARE", "1").strip() != "0" if allow_bar_fallback is None else allow_bar_fallback
        )

    def stock_universe(self) -> list[StockUniverseItem]:
        try:
            return self.client.stock_universe()
        except HistoryDataUnavailable:
            if not self.allow_bar_fallback:
                raise
            return self.fallback.stock_universe()

    def daily_bars(self, symbol: str, days: int = 250) -> list[DailyBar]:
        try:
            return self.client.history_bars(symbol, days=days, period="D", adjust="qfq")
        except HistoryDataUnavailable:
            if not self.allow_bar_fallback:
                raise
            return self.fallback.daily_bars(symbol, days=days)

    def weekly_bars(self, symbol: str, weeks: int = 80) -> list[DailyBar]:
        try:
            return self.client.history_bars(symbol, days=weeks, period="W", adjust="qfq")[-weeks:]
        except HistoryDataUnavailable:
            if not self.allow_bar_fallback:
                raise
            return self.fallback.weekly_bars(symbol, weeks=weeks)

    def theme_memberships(self, symbols: list[str]) -> list[ThemeMembership]:
        if os.getenv("THS_THEME_FALLBACK_TO_AKSHARE", "1").strip() == "0":
            return []
        return self.fallback.theme_memberships(symbols)


class DevNewsAnnouncementProvider:
    name = "dev-news-announcement"

    def news(self, symbols: list[str] | None = None) -> list[NewsItem]:
        return []

    def announcements(self, symbols: list[str] | None = None) -> list[AnnouncementItem]:
        return []


class TonghuashunNewsAnnouncementProvider:
    name = "ths-quantapi-info"

    def __init__(self, client: TonghuashunQuantApiClient | None = None):
        self.client = client or TonghuashunQuantApiClient()

    def news(self, symbols: list[str] | None = None) -> list[NewsItem]:
        return []

    def announcements(self, symbols: list[str] | None = None) -> list[AnnouncementItem]:
        return self.client.announcements(symbols)


class TushareNewsAnnouncementProvider:
    name = "tushare-pro-info"

    def __init__(
        self,
        token: str | None = None,
        endpoint: str | None = None,
        timeout_seconds: float | None = None,
        news_source: str | None = None,
    ):
        self.token = token or os.getenv("TUSHARE_TOKEN", "")
        self.endpoint = endpoint or os.getenv("TUSHARE_API_URL", "http://api.tushare.pro")
        self.timeout_seconds = timeout_seconds or float(os.getenv("TUSHARE_TIMEOUT_SECONDS", "10"))
        self.news_source = news_source or os.getenv("TUSHARE_NEWS_SRC", "sina")

    def news(self, symbols: list[str] | None = None) -> list[NewsItem]:
        start, end = _today_window()
        rows = self._call(
            "news",
            params={
                "src": self.news_source,
                "start_date": start.strftime("%Y-%m-%d %H:%M:%S"),
                "end_date": end.strftime("%Y-%m-%d %H:%M:%S"),
            },
            fields="datetime,title,content,src,url",
        )
        wanted = _symbol_codes(symbols)
        items: list[NewsItem] = []
        for row in rows:
            title = _first_text(row, "title", "content")
            if not title:
                continue
            summary = _first_text(row, "content", "summary")
            matched_symbol = _match_symbol(title + summary, wanted)
            if wanted and matched_symbol is None:
                continue
            published_at = _parse_datetime(_first_text(row, "datetime", "pub_time", "time"), fallback=end)
            item_id = _stable_id("tushare-news", matched_symbol or "market", title, published_at.isoformat())
            items.append(
                NewsItem(
                    id=item_id,
                    symbol=matched_symbol,
                    title=title[:300],
                    summary=summary[:800],
                    published_at=published_at,
                    source_url=_first_text(row, "url", "link"),
                    source_name=_first_text(row, "src", "source") or self.news_source,
                    event_type="news",
                    importance="medium",
                    provider=self.name,
                    source_id="src-tushare-news",
                    license_note="Tushare Pro 授权/积分接口，仅保存标题摘要和链接",
                )
            )
        return items[:200]

    def announcements(self, symbols: list[str] | None = None) -> list[AnnouncementItem]:
        today = datetime.now(CN_TZ).date()
        rows = self._call(
            "anns_d",
            params={"ann_date": today.strftime("%Y%m%d")},
            fields="ts_code,name,title,ann_date,url",
        )
        wanted = _symbol_codes(symbols)
        items: list[AnnouncementItem] = []
        for row in rows:
            ts_code = _first_text(row, "ts_code", "symbol")
            normalized = _normalize_tushare_symbol(ts_code)
            if wanted and _plain_code(normalized) not in wanted:
                continue
            title = _first_text(row, "title", "ann_title")
            if not title:
                continue
            published_at = _parse_datetime(_first_text(row, "ann_date", "datetime"), fallback=datetime.combine(today, time(16), CN_TZ))
            item_id = _stable_id("tushare-announcement", normalized or "market", title, published_at.isoformat())
            name = _first_text(row, "name", "sec_name")
            items.append(
                AnnouncementItem(
                    id=item_id,
                    symbol=normalized,
                    title=title[:300],
                    summary=(f"{name}：{title}" if name else title)[:800],
                    published_at=published_at,
                    source_url=_first_text(row, "url", "link"),
                    source_name="Tushare Pro 公告",
                    event_type="announcement",
                    importance=_announcement_importance(title),
                    provider=self.name,
                    source_id="src-tushare-announcement",
                    license_note="Tushare Pro 公告信息接口，仅保存标题摘要和链接",
                )
            )
        return items[:500]

    def _call(self, api_name: str, params: dict[str, Any], fields: str = "") -> list[dict[str, Any]]:
        if not self.token:
            raise RuntimeError("TUSHARE_TOKEN is required when MARKETLENS_INFO_PROVIDER=tushare.")
        try:
            response = requests.post(
                self.endpoint,
                json={"api_name": api_name, "token": self.token, "params": params, "fields": fields},
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            raise RuntimeError(f"Tushare {api_name} request failed: {exc}") from exc
        if int(payload.get("code", -1)) != 0:
            raise RuntimeError(f"Tushare {api_name} returned {payload.get('code')}: {payload.get('msg')}")
        data = payload.get("data") or {}
        output_fields = list(data.get("fields") or [])
        items = list(data.get("items") or [])
        return [dict(zip(output_fields, item)) for item in items]


def _today_window() -> tuple[datetime, datetime]:
    now = datetime.now(CN_TZ)
    start = datetime.combine(now.date(), time.min, CN_TZ)
    return start, now


def _first_text(row: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return str(value).strip()
    return ""


def _stable_id(*parts: str) -> str:
    digest = hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:16]
    return "-".join([parts[0], digest])


def _symbol_codes(symbols: list[str] | None) -> set[str]:
    return {_plain_code(symbol) for symbol in symbols or [] if symbol}


def _plain_code(symbol: str | None) -> str:
    return (symbol or "").upper().replace(".SH", "").replace(".SZ", "").replace(".BJ", "")


def _normalize_tushare_symbol(symbol: str | None) -> str | None:
    raw = (symbol or "").strip().upper()
    if not raw:
        return None
    if raw.endswith((".SH", ".SZ", ".BJ")):
        return raw
    code = _plain_code(raw)
    if code.startswith(("5", "6", "9")):
        return f"{code}.SH"
    if code.startswith(("4", "8")):
        return f"{code}.BJ"
    return f"{code}.SZ"


def _match_symbol(text: str, wanted_codes: set[str]) -> str | None:
    for code in wanted_codes:
        if code and code in text:
            return _normalize_tushare_symbol(code)
    return None


def _parse_datetime(raw: str, fallback: datetime) -> datetime:
    value = raw.strip()
    if not value:
        return fallback
    for fmt in ("%Y%m%d", "%Y-%m-%d", "%Y-%m-%d %H:%M:%S"):
        try:
            parsed = datetime.strptime(value[: _datetime_format_length(fmt)], fmt)
            if fmt in {"%Y%m%d", "%Y-%m-%d"}:
                parsed = parsed.replace(hour=16)
            return parsed.replace(tzinfo=CN_TZ)
        except ValueError:
            continue
    return fallback


def _datetime_format_length(fmt: str) -> int:
    return {
        "%Y%m%d": 8,
        "%Y-%m-%d": 10,
        "%Y-%m-%d %H:%M:%S": 19,
    }[fmt]


def _announcement_importance(title: str) -> str:
    high_terms = ("重大", "停牌", "复牌", "重组", "问询函", "监管", "处罚", "风险提示", "退市", "业绩预告")
    return "high" if any(term in title for term in high_terms) else "medium"


def build_news_announcement_provider() -> NewsAnnouncementProvider:
    provider = os.getenv("MARKETLENS_INFO_PROVIDER", "dev").strip().lower()
    if provider in {"ths", "ths_quantapi", "tonghuashun", "ifind"}:
        return TonghuashunNewsAnnouncementProvider()
    if provider == "tushare":
        return TushareNewsAnnouncementProvider()
    return DevNewsAnnouncementProvider()


def build_market_data_provider() -> MarketDataProvider:
    provider = os.getenv("MARKETLENS_MARKET_PROVIDER", "dev").strip().lower()
    if provider in {"ths", "ths_delayed", "ths_quantapi", "tonghuashun", "ifind"}:
        return TonghuashunMarketDataProvider()
    return DevMarketDataProvider()


def build_history_data_provider() -> HistoryDataProvider:
    provider = os.getenv("MARKETLENS_HISTORY_PROVIDER", "dev").strip().lower()
    if provider in {"ths", "ths_delayed", "ths_quantapi", "tonghuashun", "ifind"}:
        return TonghuashunDelayedHistoryProvider()
    return DevHistoryDataProvider()


def history_provider_sources() -> list[SourceRef]:
    if isinstance(history_data_provider, TonghuashunDelayedHistoryProvider):
        sources = [ths_delayed_source()]
        history_fallback_enabled = os.getenv("THS_HISTORY_FALLBACK_TO_AKSHARE", "1").strip() != "0"
        theme_fallback_enabled = os.getenv("THS_THEME_FALLBACK_TO_AKSHARE", "1").strip() != "0"
        if history_fallback_enabled or theme_fallback_enabled:
            sources.append(akshare_source())
        return sources
    return [history_data_provider_source()]


def market_provider_sources() -> list[SourceRef]:
    if isinstance(market_data_provider, TonghuashunMarketDataProvider):
        return [ths_market_source()]
    return [live_source(), sina_source()]


def information_provider_sources() -> list[SourceRef]:
    if isinstance(news_announcement_provider, TonghuashunNewsAnnouncementProvider):
        return [ths_announcement_source()]
    return []


def source_ref_for_id(source_id: str) -> SourceRef:
    for source in [*market_provider_sources(), *history_provider_sources(), *information_provider_sources()]:
        if source.id == source_id:
            return source
    if source_id == "src-eastmoney-live":
        return live_source()
    if source_id == "src-sina-live":
        return sina_source()
    if source_id == "src-ths-quantapi-announcement":
        return ths_announcement_source()
    return ths_market_source() if source_id.startswith("src-ths-") else live_source()


def provider_quote_rows(symbols: list[str]) -> dict[str, dict[str, Any]]:
    if hasattr(market_data_provider, "quote_rows"):
        return market_data_provider.quote_rows(symbols)  # type: ignore[attr-defined]
    return fetch_quote_rows(symbols)


def history_data_source_ids(provider: HistoryDataProvider | None = None) -> list[str]:
    selected = provider or history_data_provider
    return list(getattr(selected, "source_ids", ["src-akshare-dev"]))


def data_source_statuses() -> list[DataSourceStatus]:
    statuses: list[DataSourceStatus] = []
    ths_token_configured = bool(os.getenv("THS_ACCESS_TOKEN", "").strip() or os.getenv("THS_REFRESH_TOKEN", "").strip())
    credential_status = "configured" if ths_token_configured else "missing_credentials"
    credential_value = "configured" if ths_token_configured else "needs_token"
    credential_next_step = "" if ths_token_configured else "Set THS_REFRESH_TOKEN or THS_ACCESS_TOKEN to enable Tonghuashun iFinD QuantAPI."

    market_provider = os.getenv("MARKETLENS_MARKET_PROVIDER", "dev").strip().lower()
    history_provider = os.getenv("MARKETLENS_HISTORY_PROVIDER", "dev").strip().lower()
    info_provider = os.getenv("MARKETLENS_INFO_PROVIDER", "dev").strip().lower()
    ths_market_providers = {"ths", "ths_delayed", "ths_quantapi", "tonghuashun", "ifind"}
    ths_history_providers = {"ths", "ths_delayed", "ths_quantapi", "tonghuashun", "ifind"}
    ths_info_providers = {"ths", "ths_quantapi", "tonghuashun", "ifind"}

    if market_provider in ths_market_providers:
        statuses.append(
            DataSourceStatus(
                id="src-ths-quantapi-market",
                name="Tonghuashun iFinD QuantAPI Market",
                provider="ths-quantapi-market",
                status=credential_status,
                capabilities={
                    "quotes": credential_value,
                    "indexes": credential_value,
                    "ranked_groups": credential_value,
                },
                next_step=credential_next_step,
            )
        )

    if history_provider in ths_history_providers:
        theme_memberships = "fallback" if os.getenv("THS_THEME_FALLBACK_TO_AKSHARE", "1").strip() != "0" else "not_enabled"
        statuses.append(
            DataSourceStatus(
                id="src-ths-quantapi-delayed",
                name="Tonghuashun iFinD QuantAPI Delayed History",
                provider="ths-quantapi-delayed",
                status=credential_status,
                capabilities={
                    "history_bars": credential_value,
                    "stock_universe": credential_value,
                    "theme_memberships": theme_memberships,
                },
                next_step=credential_next_step,
            )
        )

    if info_provider in ths_info_providers:
        statuses.append(
            DataSourceStatus(
                id="src-ths-quantapi-announcement",
                name="Tonghuashun iFinD QuantAPI Announcements",
                provider="ths-quantapi-info",
                status=credential_status,
                capabilities={
                    "announcements": credential_value,
                    "news": "not_enabled",
                },
                next_step=credential_next_step,
            )
        )

    return statuses


def history_data_provider_source() -> SourceRef:
    return akshare_source()


history_data_provider: HistoryDataProvider = build_history_data_provider()
market_data_provider: MarketDataProvider = build_market_data_provider()
news_announcement_provider: NewsAnnouncementProvider = build_news_announcement_provider()


def _chunks(items: list[str], size: int) -> list[list[str]]:
    normalized_size = max(1, size)
    return [items[index : index + normalized_size] for index in range(0, len(items), normalized_size)]


def _pick(row: dict[str, Any], *keys: str) -> Any:
    lowered = {str(key).lower(): value for key, value in row.items()}
    for key in keys:
        if key in row and row[key] not in (None, ""):
            return row[key]
        value = lowered.get(key.lower())
        if value not in (None, ""):
            return value
    return None


def _number(value: Any, default: float = 0) -> float:
    try:
        if value in (None, "-", ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default
