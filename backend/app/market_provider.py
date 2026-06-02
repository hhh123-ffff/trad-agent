from __future__ import annotations

import re
import os
from datetime import datetime, timedelta, timezone
from typing import Any

import requests

from .models import (
    BriefItem,
    Confidence,
    EventType,
    MarketEvent,
    MarketIndex,
    MarketTemperature,
    PreopenBrief,
    ReplayReport,
    ReplaySection,
    SectorSnapshot,
    SourceRef,
    WatchlistStock,
)

CN_TZ = timezone(timedelta(hours=8))
EASTMONEY_UT = "bd1d9ddb04089700cf9c27f6f7426281"
QUOTE_TIMEOUT = float(os.getenv("QUOTE_TIMEOUT_SECONDS", "2"))
SINA_MARKET_URL = "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData"
SINA_QUOTE_URL = "https://hq.sinajs.cn/list="
SINA_PAGE_LIMIT = int(os.getenv("SINA_PAGE_LIMIT", "10"))
SINA_SAMPLE_SYMBOLS = [
    "600000.SH",
    "601398.SH",
    "600519.SH",
    "000001.SZ",
    "000333.SZ",
    "300750.SZ",
    "002594.SZ",
    "601318.SH",
    "600036.SH",
    "601899.SH",
    "000858.SZ",
    "300059.SZ",
    "688981.SH",
    "603259.SH",
    "002475.SZ",
    "600276.SH",
    "601857.SH",
    "601988.SH",
    "601288.SH",
    "600030.SH",
    "000063.SZ",
    "002415.SZ",
    "300760.SZ",
    "601012.SH",
    "600887.SH",
    "600309.SH",
    "002230.SZ",
    "688111.SH",
    "603288.SH",
    "300124.SZ",
]
DISCLAIMER = "本产品仅做公开/授权信息整理和复盘辅助，不构成证券投资建议、收益承诺、目标价或交易指令。"


class MarketDataUnavailable(RuntimeError):
    pass


def live_source() -> SourceRef:
    return SourceRef(
        id="src-eastmoney-live",
        name="东方财富实时行情",
        url="https://quote.eastmoney.com/",
        as_of=datetime.now(CN_TZ),
        license="public-dev-source",
        freshness="实时或最近交易日行情；商业化生产环境应替换为授权行情源",
    )


def sina_source() -> SourceRef:
    return SourceRef(
        id="src-sina-live",
        name="新浪财经实时行情",
        url="https://finance.sina.com.cn/realstock/",
        as_of=datetime.now(CN_TZ),
        license="public-dev-source",
        freshness="实时或最近交易日行情；作为开发备用源，商业化生产环境应替换为授权行情源",
    )


def _get_json(url: str, params: dict[str, Any]) -> dict[str, Any]:
    try:
        response = requests.get(
            url,
            params=params,
            timeout=QUOTE_TIMEOUT,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) MarketLens/0.2",
                "Referer": "https://quote.eastmoney.com/",
                "Accept": "application/json,text/plain,*/*",
            },
        )
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        raise MarketDataUnavailable(f"实时行情源不可用：{exc}") from exc
    if not isinstance(payload, dict):
        raise MarketDataUnavailable("实时行情源返回格式异常。")
    return payload


def _get_sina_json(params: dict[str, Any]) -> list[dict[str, Any]]:
    try:
        response = requests.get(
            SINA_MARKET_URL,
            params=params,
            timeout=QUOTE_TIMEOUT,
            headers={"User-Agent": "Mozilla/5.0 MarketLens/0.2", "Referer": "https://finance.sina.com.cn"},
        )
        response.raise_for_status()
        response.encoding = "gbk"
        payload = response.json()
    except Exception as exc:
        raise MarketDataUnavailable(f"新浪财经行情源不可用：{exc}") from exc
    if not isinstance(payload, list):
        raise MarketDataUnavailable("新浪财经行情源返回格式异常。")
    return payload


def _get_sina_text(codes: list[str]) -> str:
    try:
        response = requests.get(
            SINA_QUOTE_URL + ",".join(codes),
            timeout=QUOTE_TIMEOUT,
            headers={"User-Agent": "Mozilla/5.0 MarketLens/0.2", "Referer": "https://finance.sina.com.cn"},
        )
        response.raise_for_status()
        response.encoding = "gb18030"
        return response.text
    except Exception as exc:
        raise MarketDataUnavailable(f"新浪财经报价源不可用：{exc}") from exc


def _number(value: Any, default: float = 0) -> float:
    try:
        if value in (None, "-", ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _secid(symbol: str) -> str:
    code = symbol.split(".")[0]
    if symbol.endswith(".SH") or code.startswith(("5", "6", "9")):
        return f"1.{code}"
    return f"0.{code}"


def _symbol_from_code(code: str) -> str:
    if code.startswith(("5", "6", "9")):
        return f"{code}.SH"
    return f"{code}.SZ"


def _sina_code(symbol: str) -> str:
    code = symbol.split(".")[0].lower()
    upper = symbol.upper()
    if upper.endswith(".SH") or code.startswith(("5", "6", "9")):
        return f"sh{code}"
    if upper.endswith(".BJ") or code.startswith(("4", "8")):
        return f"bj{code}"
    return f"sz{code}"


def _symbol_from_sina_code(code: str) -> str:
    raw = code.lower()
    digits = raw[2:]
    if raw.startswith("sh"):
        return f"{digits}.SH"
    if raw.startswith("bj"):
        return f"{digits}.BJ"
    return f"{digits}.SZ"


def _parse_sina_assignments(text: str) -> dict[str, list[str]]:
    matches = re.finditer(r'var hq_str_([^=]+)="(.*?)";', text, flags=re.S)
    return {match.group(1): match.group(2).split(",") for match in matches if match.group(2)}


def fetch_indexes() -> list[MarketIndex]:
    payload = _get_json(
        "https://push2.eastmoney.com/api/qt/ulist.np/get",
        {
            "fltt": "2",
            "invt": "2",
            "ut": EASTMONEY_UT,
            "secids": "1.000001,0.399001,0.399006",
            "fields": "f12,f14,f2,f3,f6",
        },
    )
    rows = payload.get("data", {}).get("diff") or []
    if not rows:
        raise MarketDataUnavailable("未获取到指数行情。")
    indexes: list[MarketIndex] = []
    for row in rows:
        code = str(row.get("f12", ""))
        indexes.append(
            MarketIndex(
                symbol="000001.SH" if code == "000001" else f"{code}.SZ",
                name=str(row.get("f14", code)),
                value=_number(row.get("f2")),
                change_pct=_number(row.get("f3")),
                turnover_billion=round(_number(row.get("f6")) / 100_000_000, 2),
                source_id="src-eastmoney-live",
            )
        )
    return indexes


def fetch_sina_indexes() -> list[MarketIndex]:
    fields_by_code = _parse_sina_assignments(_get_sina_text(["s_sh000001", "s_sz399001", "s_sz399006"]))
    mapping = {
        "s_sh000001": "000001.SH",
        "s_sz399001": "399001.SZ",
        "s_sz399006": "399006.SZ",
    }
    indexes: list[MarketIndex] = []
    for sina_code, symbol in mapping.items():
        fields = fields_by_code.get(sina_code) or []
        if len(fields) < 4:
            continue
        indexes.append(
            MarketIndex(
                symbol=symbol,
                name=fields[0],
                value=_number(fields[1]),
                change_pct=_number(fields[3]),
                turnover_billion=round(_number(fields[5] if len(fields) > 5 else 0) / 10_000, 2),
                source_id="src-sina-live",
            )
        )
    if not indexes:
        raise MarketDataUnavailable("未获取到新浪指数行情。")
    return indexes


def fetch_a_share_snapshot() -> tuple[MarketTemperature, dict[str, dict[str, Any]]]:
    payload = _get_json(
        "https://push2.eastmoney.com/api/qt/clist/get",
        {
            "pn": "1",
            "pz": "6000",
            "po": "1",
            "np": "1",
            "fltt": "2",
            "invt": "2",
            "fid": "f3",
            "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23",
            "fields": "f12,f14,f2,f3,f6,f10",
            "ut": EASTMONEY_UT,
        },
    )
    rows = payload.get("data", {}).get("diff") or []
    if not rows:
        raise MarketDataUnavailable("未获取到 A 股全市场行情。")
    advancers = sum(1 for row in rows if _number(row.get("f3")) > 0)
    decliners = sum(1 for row in rows if _number(row.get("f3")) < 0)
    limit_up = sum(1 for row in rows if _number(row.get("f3")) >= 9.8)
    limit_down = sum(1 for row in rows if _number(row.get("f3")) <= -9.8)
    turnover_billion = round(sum(_number(row.get("f6")) for row in rows) / 100_000_000, 2)
    total_directional = max(advancers + decliners, 1)
    score = round(advancers / total_directional * 100)
    label = "偏活跃" if score >= 60 else "偏弱" if score <= 40 else "均衡"
    quotes = {_symbol_from_code(str(row.get("f12", ""))): row for row in rows if row.get("f12")}
    return (
        MarketTemperature(
            score=max(0, min(100, score)),
            label=label,
            advancers=advancers,
            decliners=decliners,
            limit_up_count=limit_up,
            limit_down_count=limit_down,
            total_turnover_billion=turnover_billion,
            updated_at=datetime.now(CN_TZ),
        ),
        quotes,
    )


def _fetch_sina_market_page(page: int) -> list[dict[str, Any]]:
    return _get_sina_json(
        {
            "page": page,
            "num": 100,
            "sort": "symbol",
            "asc": 1,
            "node": "hs_a",
            "symbol": "",
            "_s_r_a": "page",
        }
    )


def fetch_sina_a_share_snapshot() -> tuple[MarketTemperature, dict[str, dict[str, Any]], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    last_error = ""
    for page in range(1, SINA_PAGE_LIMIT + 1):
        try:
            page_rows = _fetch_sina_market_page(page)
        except Exception as exc:
            last_error = str(exc)
            break
        if not page_rows:
            break
        rows.extend(page_rows)
        if len(page_rows) < 100:
            break

    valid_rows = [row for row in rows if _number(row.get("trade")) > 0 and row.get("symbol")]
    if len(valid_rows) < 1000:
        detail = last_error or "返回有效股票数量不足。"
        raise MarketDataUnavailable(f"未获取到足够的新浪 A 股行情：{detail}")

    advancers = sum(1 for row in valid_rows if _number(row.get("changepercent")) > 0)
    decliners = sum(1 for row in valid_rows if _number(row.get("changepercent")) < 0)
    limit_up = sum(1 for row in valid_rows if _number(row.get("changepercent")) >= 9.8)
    limit_down = sum(1 for row in valid_rows if _number(row.get("changepercent")) <= -9.8)
    turnover_billion = round(sum(_number(row.get("amount")) for row in valid_rows) / 100_000_000, 2)
    total_directional = max(advancers + decliners, 1)
    score = round(advancers / total_directional * 100)
    label = "偏活跃" if score >= 60 else "偏弱" if score <= 40 else "均衡"
    quotes = {
        _symbol_from_sina_code(str(row["symbol"])): {
            "f14": row.get("name"),
            "f2": row.get("trade"),
            "f3": row.get("changepercent"),
            "f10": 1,
            "_source_id": "src-sina-live",
        }
        for row in valid_rows
    }
    return (
        MarketTemperature(
            score=max(0, min(100, score)),
            label=label,
            advancers=advancers,
            decliners=decliners,
            limit_up_count=limit_up,
            limit_down_count=limit_down,
            total_turnover_billion=turnover_billion,
            updated_at=datetime.now(CN_TZ),
        ),
        quotes,
        valid_rows,
    )


def fetch_sina_sample_snapshot() -> tuple[MarketTemperature, dict[str, dict[str, Any]], list[dict[str, Any]]]:
    quotes = fetch_sina_quote_rows(SINA_SAMPLE_SYMBOLS)
    rows = [
        {
            "symbol": _sina_code(symbol),
            "name": row.get("f14"),
            "trade": row.get("f2"),
            "changepercent": row.get("f3"),
            "amount": row.get("_amount", 0),
            "turnoverratio": 0,
        }
        for symbol, row in quotes.items()
    ]
    if len(rows) < 10:
        raise MarketDataUnavailable("未获取到足够的新浪样本报价。")
    advancers = sum(1 for row in rows if _number(row.get("changepercent")) > 0)
    decliners = sum(1 for row in rows if _number(row.get("changepercent")) < 0)
    limit_up = sum(1 for row in rows if _number(row.get("changepercent")) >= 9.8)
    limit_down = sum(1 for row in rows if _number(row.get("changepercent")) <= -9.8)
    total_directional = max(advancers + decliners, 1)
    score = round(advancers / total_directional * 100)
    base_label = "活跃" if score >= 60 else "偏弱" if score <= 40 else "均衡"
    return (
        MarketTemperature(
            score=max(0, min(100, score)),
            label=f"样本{base_label}",
            advancers=advancers,
            decliners=decliners,
            limit_up_count=limit_up,
            limit_down_count=limit_down,
            total_turnover_billion=round(sum(_number(row.get("amount")) for row in rows) / 100_000_000, 2),
            updated_at=datetime.now(CN_TZ),
        ),
        quotes,
        rows,
    )


def fetch_sectors(limit: int = 8) -> list[SectorSnapshot]:
    payload = _get_json(
        "https://push2.eastmoney.com/api/qt/clist/get",
        {
            "pn": "1",
            "pz": str(limit),
            "po": "1",
            "np": "1",
            "fltt": "2",
            "invt": "2",
            "fid": "f3",
            "fs": "m:90+t:2",
            "fields": "f12,f14,f3,f6,f128,f140",
            "ut": EASTMONEY_UT,
        },
    )
    rows = payload.get("data", {}).get("diff") or []
    if not rows:
        raise MarketDataUnavailable("未获取到行业板块行情。")
    sectors: list[SectorSnapshot] = []
    for row in rows:
        name = str(row.get("f14", "板块"))
        leader = str(row.get("f128") or row.get("f140") or "")
        sectors.append(
            SectorSnapshot(
                name=name,
                change_pct=_number(row.get("f3")),
                turnover_billion=round(_number(row.get("f6")) / 100_000_000, 2),
                leading_symbols=[leader] if leader else [],
                driver=f"{name}板块按实时涨幅排序靠前，需结合成交额和成分股联动继续验证。",
                confidence=Confidence.medium,
                source_id="src-eastmoney-live",
            )
        )
    return sectors


def build_sina_market_groups(rows: list[dict[str, Any]]) -> list[SectorSnapshot]:
    valid_rows = [row for row in rows if _number(row.get("trade")) > 0 and row.get("symbol")]

    def symbols(sample: list[dict[str, Any]]) -> list[str]:
        return [_symbol_from_sina_code(str(row["symbol"])) for row in sample[:5]]

    def names(sample: list[dict[str, Any]]) -> str:
        return "、".join(str(row.get("name") or row.get("code")) for row in sample[:3])

    gainers = sorted(valid_rows, key=lambda row: _number(row.get("changepercent")), reverse=True)[:10]
    decliners = sorted(valid_rows, key=lambda row: _number(row.get("changepercent")))[:10]
    amount_leaders = sorted(valid_rows, key=lambda row: _number(row.get("amount")), reverse=True)[:10]
    turnover_leaders = sorted(valid_rows, key=lambda row: _number(row.get("turnoverratio")), reverse=True)[:10]
    groups = [
        ("A股涨幅榜", gainers, "涨幅靠前"),
        ("A股跌幅榜", decliners, "跌幅靠前"),
        ("成交额排行", amount_leaders, "成交额靠前"),
        ("换手率排行", turnover_leaders, "换手率靠前"),
    ]
    snapshots: list[SectorSnapshot] = []
    for name, sample, driver_prefix in groups:
        if not sample:
            continue
        snapshots.append(
            SectorSnapshot(
                name=name,
                change_pct=round(sum(_number(row.get("changepercent")) for row in sample) / len(sample), 2),
                turnover_billion=round(sum(_number(row.get("amount")) for row in sample) / 100_000_000, 2),
                leading_symbols=symbols(sample),
                driver=f"{driver_prefix}：{names(sample)}。该分组来自新浪财经实时行情列表，不代表行业分类。",
                confidence=Confidence.medium,
                source_id="src-sina-live",
            )
        )
    return snapshots


def fetch_quote_rows(symbols: list[str]) -> dict[str, dict[str, Any]]:
    if not symbols:
        return {}
    try:
        payload = _get_json(
            "https://push2.eastmoney.com/api/qt/ulist.np/get",
            {
                "fltt": "2",
                "invt": "2",
                "ut": EASTMONEY_UT,
                "secids": ",".join(_secid(symbol.upper()) for symbol in symbols),
                "fields": "f12,f14,f2,f3,f10",
            },
        )
        rows = payload.get("data", {}).get("diff") or []
        return {
            _symbol_from_code(str(row.get("f12", ""))): {**row, "_source_id": "src-eastmoney-live"}
            for row in rows
            if row.get("f12")
        }
    except MarketDataUnavailable:
        return fetch_sina_quote_rows(symbols)


def fetch_sina_quote_rows(symbols: list[str]) -> dict[str, dict[str, Any]]:
    assignments = _parse_sina_assignments(_get_sina_text([_sina_code(symbol.upper()) for symbol in symbols]))
    quotes: dict[str, dict[str, Any]] = {}
    for sina_code, fields in assignments.items():
        if len(fields) < 4 or not fields[0]:
            continue
        latest = _number(fields[3])
        previous_close = _number(fields[2])
        change_pct = round((latest - previous_close) / previous_close * 100, 2) if previous_close else 0
        quotes[_symbol_from_sina_code(sina_code)] = {
            "f14": fields[0],
            "f2": latest,
            "f3": change_pct,
            "f10": 1,
            "_amount": _number(fields[9] if len(fields) > 9 else 0),
            "_source_id": "src-sina-live",
        }
    return quotes


def enrich_watchlist(items: list[WatchlistStock], cached_quotes: dict[str, dict[str, Any]] | None = None) -> list[WatchlistStock]:
    if not items:
        return []
    quotes = dict(cached_quotes or {})
    missing = [item.symbol for item in items if item.symbol not in quotes]
    quotes.update(fetch_quote_rows(missing))
    enriched: list[WatchlistStock] = []
    for item in items:
        row = quotes.get(item.symbol)
        if not row:
            raise MarketDataUnavailable(f"未获取到 {item.symbol} 的实时行情。")
        latest = _number(row.get("f2"))
        change_pct = _number(row.get("f3"))
        volume_ratio = _number(row.get("f10"), 1)
        source_id = str(row.get("_source_id") or item.source_id or "src-eastmoney-live")
        enriched.append(
            item.model_copy(
                update={
                    "name": str(row.get("f14") or item.name),
                    "price": latest,
                    "change_pct": change_pct,
                    "volume_ratio": volume_ratio,
                    "latest_event": f"实时行情：{latest:.2f}，涨跌幅 {change_pct:+.2f}%。",
                    "source_id": source_id,
                }
            )
        )
    return enriched


def build_market_events(
    temperature: MarketTemperature,
    sectors: list[SectorSnapshot],
    watchlist: list[WatchlistStock],
    source_id: str,
) -> list[MarketEvent]:
    now = datetime.now(CN_TZ)
    events: list[MarketEvent] = [
        MarketEvent(
            id=f"live-breadth-{now:%Y%m%d%H%M}",
            occurred_at=now,
            type=EventType.capital_flow,
            title="A股市场宽度实时快照",
            summary=f"上涨 {temperature.advancers} 家，下跌 {temperature.decliners} 家，涨停 {temperature.limit_up_count} 家，跌停 {temperature.limit_down_count} 家。",
            affected_symbols=[],
            affected_sectors=[],
            importance="high" if temperature.score >= 65 or temperature.score <= 35 else "medium",
            fact_basis=[
                f"市场温度 {temperature.score}",
                f"全市场成交额 {temperature.total_turnover_billion:.0f} 亿",
            ],
            inference="市场温度来自实时涨跌家数，不构成方向预测。",
            confidence=Confidence.high,
            source_ids=[source_id],
            compliance_label="fact",
        )
    ]
    for sector in sectors[:3]:
        events.append(
            MarketEvent(
                id=f"live-sector-{sector.name}-{now:%Y%m%d%H%M}",
                occurred_at=now,
                type=EventType.sector_rotation,
                title=f"{sector.name}板块实时靠前",
                summary=f"{sector.name}板块涨跌幅 {sector.change_pct:+.2f}%，成交额约 {sector.turnover_billion:.0f} 亿。",
                affected_symbols=sector.leading_symbols,
                affected_sectors=[sector.name],
                importance="high" if abs(sector.change_pct) >= 3 else "medium",
                fact_basis=[f"板块涨跌幅 {sector.change_pct:+.2f}%", f"成交额 {sector.turnover_billion:.0f} 亿"],
                inference="仅表示当前板块排序靠前，需结合后续成交和成分股扩散验证。",
                confidence=Confidence.medium,
                source_ids=[source_id],
                compliance_label="inference",
            )
        )
    for item in watchlist:
        if abs(item.change_pct) >= 5 or item.volume_ratio >= 2:
            events.append(
                MarketEvent(
                    id=f"live-watchlist-{item.symbol}-{now:%Y%m%d%H%M}",
                    occurred_at=now,
                    type=EventType.watchlist,
                    title=f"{item.name}出现自选股异动",
                    summary=f"{item.symbol} 最新价 {item.price:.2f}，涨跌幅 {item.change_pct:+.2f}%，量比 {item.volume_ratio:.2f}。",
                    affected_symbols=[item.symbol],
                    affected_sectors=item.tags[:2],
                    importance="high",
                    fact_basis=[f"涨跌幅 {item.change_pct:+.2f}%", f"量比 {item.volume_ratio:.2f}"],
                    inference="该事件来自实时行情规则触发，不代表买卖建议。",
                    confidence=Confidence.high,
                    source_ids=[source_id],
                    compliance_label="fact",
                )
            )
    return events


def build_live_preopen(
    temperature: MarketTemperature,
    sectors: list[SectorSnapshot],
    watchlist: list[WatchlistStock],
    source: SourceRef | None = None,
) -> PreopenBrief:
    now = datetime.now(CN_TZ)
    source_ref = source or live_source()
    top_sector = sectors[0]
    watched = watchlist[:3]
    return PreopenBrief(
        generated_at=now,
        version=now.strftime("%H:%M"),
        readiness=100,
        must_watch=[
            BriefItem(
                title="先看市场宽度与成交额",
                detail=f"当前上涨 {temperature.advancers} 家、下跌 {temperature.decliners} 家，成交额约 {temperature.total_turnover_billion:.0f} 亿。",
                importance="high",
                impact_scope=["全市场"],
                source_ids=[source_ref.id],
            )
        ],
        watchlist_impacts=[
            BriefItem(
                title=f"{item.name} 实时自选股状态",
                detail=f"{item.symbol} 最新价 {item.price:.2f}，涨跌幅 {item.change_pct:+.2f}%，量比 {item.volume_ratio:.2f}。",
                importance="high" if abs(item.change_pct) >= 5 else "medium",
                impact_scope=[item.symbol],
                source_ids=[source_ref.id],
            )
            for item in watched
        ],
        sector_clues=[
            BriefItem(
                title=f"{top_sector.name}板块排序靠前",
                detail=f"板块涨跌幅 {top_sector.change_pct:+.2f}%，成交额约 {top_sector.turnover_billion:.0f} 亿。",
                importance="medium",
                impact_scope=[top_sector.name],
                source_ids=[source_ref.id],
            )
        ],
        risk_events=[
            BriefItem(
                title="仅基于实时行情，不含公告全文审阅",
                detail="当前版本未接入授权公告源，因此不展示公告风险判断。",
                importance="medium",
                impact_scope=["合规边界"],
                source_ids=[source_ref.id],
            )
        ],
        calendar=[],
        sources=[source_ref],
    )


def build_live_replay(
    events: list[MarketEvent],
    temperature: MarketTemperature,
    sectors: list[SectorSnapshot],
    source: SourceRef | None = None,
) -> ReplayReport:
    now = datetime.now(CN_TZ)
    source_ref = source or live_source()
    top_sector = sectors[0]
    return ReplayReport(
        trading_day=now.strftime("%Y-%m-%d"),
        generated_at=now,
        headline=f"实时复盘：市场温度 {temperature.score}，{top_sector.name}板块当前排序靠前。",
        market_summary=f"上涨 {temperature.advancers} 家，下跌 {temperature.decliners} 家，成交额约 {temperature.total_turnover_billion:.0f} 亿。",
        sections=[
            ReplaySection(
                window="实时快照",
                title="市场宽度与板块排序",
                summary=f"{top_sector.name}板块涨跌幅 {top_sector.change_pct:+.2f}%，当前复盘仅基于实时行情源。",
                missed_signals=events,
                source_ids=[source_ref.id],
            )
        ],
        watchlist_summary=[],
        sources=[source_ref],
    )


def live_market_bundle(watchlist: list[WatchlistStock]) -> tuple[
    MarketTemperature,
    list[MarketIndex],
    list[SectorSnapshot],
    list[WatchlistStock],
    list[MarketEvent],
    SourceRef,
]:
    try:
        temperature, quotes = fetch_a_share_snapshot()
        indexes = fetch_indexes()
        sectors = fetch_sectors()
        source = live_source()
    except MarketDataUnavailable:
        try:
            temperature, quotes, rows = fetch_sina_a_share_snapshot()
        except MarketDataUnavailable:
            temperature, quotes, rows = fetch_sina_sample_snapshot()
        indexes = fetch_sina_indexes()
        sectors = build_sina_market_groups(rows)
        source = sina_source()
    enriched_watchlist = enrich_watchlist(watchlist, quotes) if watchlist else []
    events = build_market_events(temperature, sectors, enriched_watchlist, source.id)
    return temperature, indexes, sectors, enriched_watchlist, events, source
