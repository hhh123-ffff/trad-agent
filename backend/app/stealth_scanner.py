from __future__ import annotations

from collections import Counter
from datetime import date
from typing import Any, Callable, Sequence

import numpy as np
import pandas as pd

from .data_providers import history_data_provider, history_data_source_ids
from .history_provider import HistoryDataUnavailable, fetch_stock_market_profiles
from .models import DailyBar, StealthCandidate, StealthScanRunResponse, StockUniverseItem, ThemeMembership
from .repositories import list_watchlist
from .stealth_repository import save_daily_bars, save_scan_results, save_theme_memberships, save_universe_items


MIN_HISTORY_BARS = 120
MIN_AVG_AMOUNT = 50_000_000
MAINBOARD_FLOAT_CAP_MIN_BILLION = 50
MAINBOARD_FLOAT_CAP_MAX_BILLION = 200
ScanProgressCallback = Callable[[dict[str, Any]], None]
ScanFailureCallback = Callable[[dict[str, Any]], None]
ScanSuccessCallback = Callable[[str], None]


def _clip(value: float) -> float:
    if np.isnan(value) or np.isinf(value):
        return 0
    return round(float(max(0, min(100, value))), 2)


def _frame(bars: Sequence[DailyBar]) -> pd.DataFrame:
    return pd.DataFrame([bar.model_dump() for bar in bars]).sort_values("trade_date").reset_index(drop=True)


def _is_mainboard_symbol(symbol: str) -> bool:
    code = symbol.split(".")[0]
    suffix = symbol.split(".")[-1].upper() if "." in symbol else ""
    return (suffix == "SH" and code.startswith(("600", "601", "603", "605"))) or (
        suffix == "SZ" and code.startswith(("000", "001", "002", "003"))
    )


def _profile_number(profile: dict[str, Any], *keys: str) -> float:
    for key in keys:
        value = profile.get(key)
        if value in (None, "", "-"):
            continue
        try:
            return float(str(value).replace(",", ""))
        except ValueError:
            continue
    return 0.0


def _is_step_up(values: Sequence[float], min_steps: int = 3) -> bool:
    clean = [float(value or 0) for value in values]
    if len(clean) < min_steps + 1:
        return False
    increases = sum(1 for left, right in zip(clean, clean[1:]) if right > left * 1.03)
    return increases >= min_steps


def evaluate_candidate(
    item: StockUniverseItem,
    daily_bars: Sequence[DailyBar],
    weekly_bars: Sequence[DailyBar] | None = None,
    themes: Sequence[ThemeMembership] | None = None,
    active_themes: Sequence[str] | None = None,
    source_ids: Sequence[str] | None = None,
    market_profile: dict[str, Any] | None = None,
) -> StealthCandidate:
    trading_day = daily_bars[-1].trade_date if daily_bars else date.today()
    theme_names = sorted({theme.theme_name for theme in themes or []})
    evidence: list[str] = []
    risks: list[str] = []
    metrics: dict[str, float | str | int] = {}

    if item.is_st or "ST" in item.name.upper():
        risks.append("ST 或退市风险标的，默认排除。")
        return _candidate(item, trading_day, "数据不足", 0, 0, 0, 0, 100, evidence, risks, metrics, theme_names, source_ids)

    metrics["strategy_profile"] = "mainboard_volume_price"
    metrics["mainboard_match"] = "yes" if _is_mainboard_symbol(item.symbol) else "no"
    if not _is_mainboard_symbol(item.symbol):
        risks.append("仅筛选沪深主板标的，科创板、创业板、北交所不进入主候选。")
        return _candidate(item, trading_day, "数据不足", 0, 0, 0, 0, 100, evidence, risks, metrics, theme_names, source_ids)

    effective_listed_days = item.listed_days
    listing_age_source = "provider"
    if effective_listed_days <= 0 and daily_bars:
        effective_listed_days = max((daily_bars[-1].trade_date - daily_bars[0].trade_date).days, 0)
        listing_age_source = "history_span"
    metrics["listed_days"] = effective_listed_days
    metrics["listing_age_source"] = listing_age_source
    if effective_listed_days <= 0:
        risks.append("上市时间数据缺失，无法确认是否已上市满 120 天。")
        return _candidate(item, trading_day, "数据不足", 0, 0, 0, 0, 90, evidence, risks, metrics, theme_names, source_ids)
    if effective_listed_days < 120:
        risks.append(f"上市时间或可验证历史跨度约 {effective_listed_days} 天，未满 120 天，暂不纳入主板量价启动池。")
        return _candidate(item, trading_day, "数据不足", 0, 0, 0, 0, 90, evidence, risks, metrics, theme_names, source_ids)

    if len(daily_bars) < MIN_HISTORY_BARS:
        risks.append(f"历史日线不足 {MIN_HISTORY_BARS} 根，无法识别长周期结构。")
        return _candidate(item, trading_day, "数据不足", 0, 0, 0, 0, 80, evidence, risks, metrics, theme_names, source_ids)

    df = _frame(daily_bars)
    close = df["close"].astype(float)
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    amount = df["amount"].astype(float)
    change_pct = df["change_pct"].astype(float)
    last_close = float(close.iloc[-1])
    last_change = float(change_pct.iloc[-1])
    avg_amount20 = float(amount.tail(20).mean())
    avg_amount60 = float(amount.tail(60).mean())
    avg_amount120 = float(amount.tail(120).mean())
    range60 = float((high.tail(60).max() - low.tail(60).min()) / max(last_close, 0.01) * 100)
    range120 = float((high.tail(120).max() - low.tail(120).min()) / max(last_close, 0.01) * 100)
    vol20 = float(close.pct_change().tail(20).std() or 0)
    vol60 = float(close.pct_change().tail(60).std() or 0)
    ma5 = float(close.tail(5).mean())
    ma10 = float(close.tail(10).mean())
    ma20 = float(close.tail(20).mean())
    ma60 = float(close.tail(60).mean())
    ma120 = float(close.tail(120).mean())
    prior60_high = float(high.iloc[:-1].tail(60).max())
    prior120_high = float(high.iloc[:-1].tail(120).max())
    amount_ratio20 = float(amount.iloc[-1] / max(avg_amount20, 1))
    volume = df["volume"].astype(float)
    volume_ratio20 = float(volume.iloc[-1] / max(float(volume.tail(20).mean()), 1))
    ret10 = float((last_close / max(float(close.iloc[-11]), 0.01) - 1) * 100) if len(close) > 11 else 0
    limit_like_days = int((change_pct.tail(10) >= 9.6).sum())
    last_turnover = float(df["turnover_rate"].astype(float).iloc[-1])
    profile = market_profile or {}
    float_market_cap_billion = _profile_number(profile, "float_market_cap_billion", "float_market_cap")
    volume_ratio = _profile_number(profile, "volume_ratio", "vol_ratio") or round(volume_ratio20, 2)
    close_position = (last_close - float(low.iloc[-1])) / max(float(high.iloc[-1] - low.iloc[-1]), 0.01)
    ma20_prev = float(close.iloc[-25:-5].mean()) if len(close) >= 25 else ma20
    ma_alignment = ma5 > ma10 > ma20 and ma20 >= ma20_prev
    amount_step_up = _is_step_up(amount.tail(5).tolist())
    volume_step_up = _is_step_up(volume.tail(5).tolist())
    pressure_distance_60d = round((prior60_high / max(last_close, 0.01) - 1) * 100, 2)
    pressure_distance_120d = round((prior120_high / max(last_close, 0.01) - 1) * 100, 2)
    intraday_proxy = "strong_close" if close_position >= 0.72 and last_close >= ma5 else "partial" if last_close >= ma5 else "weak"

    metrics.update(
        {
            "float_market_cap_billion": round(float_market_cap_billion, 2),
            "change_pct": round(last_change, 2),
            "volume_ratio": round(volume_ratio, 2),
            "turnover_rate": round(last_turnover, 2),
            "amount_ratio_20d": round(amount_ratio20, 2),
            "volume_ratio_20d": round(volume_ratio20, 2),
            "amount_step_up": "yes" if amount_step_up else "no",
            "volume_step_up": "yes" if volume_step_up else "no",
            "ma_alignment": "bullish" if ma_alignment else "not_bullish",
            "pressure_distance_60d_pct": pressure_distance_60d,
            "pressure_distance_120d_pct": pressure_distance_120d,
            "close_position_pct": round(close_position * 100, 2),
            "intraday_proxy": intraday_proxy,
            "minute_data_status": "missing",
        }
    )

    if float_market_cap_billion <= 0:
        risks.append("流通市值数据缺失，无法确认 50 亿-200 亿主板中盘范围。")
        return _candidate(item, trading_day, "数据不足", 0, 0, 0, 0, 85, evidence, risks, metrics, theme_names, source_ids)
    if not MAINBOARD_FLOAT_CAP_MIN_BILLION <= float_market_cap_billion <= MAINBOARD_FLOAT_CAP_MAX_BILLION:
        risks.append(f"流通市值约 {float_market_cap_billion:.1f} 亿，不在 50 亿-200 亿主池。")
        return _candidate(item, trading_day, "数据不足", 0, 0, 0, 0, 80, evidence, risks, metrics, theme_names, source_ids)
    if not 2.5 <= last_change <= 6:
        risks.append(f"当日涨幅 {last_change:.2f}% 不在 2.5%-6% 的启动观察区间。")
        return _candidate(item, trading_day, "数据不足", 0, 0, 0, 0, 70, evidence, risks, metrics, theme_names, source_ids)
    if not 4 <= last_turnover <= 12:
        risks.append(f"换手率 {last_turnover:.2f}% 不在 4%-12% 的活跃观察区间。")
        return _candidate(item, trading_day, "数据不足", 0, 0, 0, 0, 70, evidence, risks, metrics, theme_names, source_ids)
    if amount_ratio20 < 1.15 or volume_ratio20 < 1.05:
        risks.append("当日成交额/成交量未明显高于近 20 日均值，量能确认不足。")
        return _candidate(item, trading_day, "数据不足", 0, 0, 0, 0, 65, evidence, risks, metrics, theme_names, source_ids)
    if not amount_step_up or not volume_step_up:
        risks.append("近 5 日成交额与成交量未同时形成台阶式放大，量价启动结构不完整。")
        return _candidate(item, trading_day, "数据不足", 0, 0, 0, 0, 65, evidence, risks, metrics, theme_names, source_ids)
    if not ma_alignment:
        risks.append("尚未形成收盘价 > MA5 > MA10 > MA20 且 MA20 上行的多头排列。")
        return _candidate(item, trading_day, "数据不足", 0, 0, 0, 0, 60, evidence, risks, metrics, theme_names, source_ids)

    evidence.append(
        f"主板量价启动：涨幅 {last_change:.2f}%，量比 {volume_ratio:.2f}，换手率 {last_turnover:.2f}%，流通市值约 {float_market_cap_billion:.0f} 亿。"
    )
    if amount_step_up and volume_step_up:
        evidence.append("近 5 日成交额与成交量呈台阶式放大。")
    elif amount_step_up:
        evidence.append("近 5 日成交额呈台阶式放大，成交量仍需继续观察。")
    evidence.append("5/10/20 日均线多头排列，且 20 日均线保持上行。")
    if intraday_proxy == "strong_close":
        evidence.append("分时代理指标偏强：收盘接近日内高位且未跌破短期均线。")
    else:
        risks.append("未接入分钟线，分时均价线与尾盘回踩条件仅用日线代理判断。")

    accumulation = 0.0
    accumulation += 20
    if 80 <= float_market_cap_billion <= 160:
        accumulation += 12
    elif MAINBOARD_FLOAT_CAP_MIN_BILLION <= float_market_cap_billion <= MAINBOARD_FLOAT_CAP_MAX_BILLION:
        accumulation += 8
    if ma_alignment:
        accumulation += 24
    if pressure_distance_60d <= 3:
        accumulation += 18
    elif pressure_distance_60d <= 8:
        accumulation += 10
    if pressure_distance_120d <= 5:
        accumulation += 10
    if close_position >= 0.72:
        accumulation += 8
    if range120 <= 35:
        accumulation += 22
        evidence.append(f"120日区间振幅约 {range120:.1f}%，长周期波动收敛。")
    if range60 <= 25:
        accumulation += 18
        evidence.append(f"60日区间振幅约 {range60:.1f}%，平台结构较紧。")
    if vol20 < vol60 * 0.85:
        accumulation += 15
        evidence.append("20日波动率低于60日波动率，短期波动继续压缩。")
    if avg_amount20 <= avg_amount60 * 1.15:
        accumulation += 10
        evidence.append("20日平均成交额未明显放大，仍处于温和观察区。")
    if avg_amount60 >= avg_amount120 * 0.95:
        accumulation += 10
        evidence.append("60日成交额没有明显萎缩，承接仍在。")
    if last_close >= ma20:
        accumulation += 10
    if last_close >= ma60:
        accumulation += 10
        evidence.append("收盘价重新站在60日均线之上。")
    if last_close >= ma120:
        accumulation += 5

    launch = 0.0
    if 3 <= last_change <= 5:
        launch += 24
    elif 2.5 <= last_change <= 6:
        launch += 16
    if 5 <= last_turnover <= 10:
        launch += 18
    else:
        launch += 10
    if 1.2 <= volume_ratio <= 2.5:
        launch += 14
    elif volume_ratio > 2.5:
        launch += 8
    if amount_step_up:
        launch += 14
    if volume_step_up:
        launch += 10
    if intraday_proxy == "strong_close":
        launch += 10
    if last_close >= prior60_high * 0.995:
        launch += 28
        evidence.append("收盘价接近或突破60日平台高点。")
    if last_close >= prior120_high * 0.995:
        launch += 18
        evidence.append("收盘价接近或突破120日压力区。")
    if amount_ratio20 >= 1.8:
        launch += 24
        evidence.append(f"当日成交额约为20日均额 {amount_ratio20:.1f} 倍，出现启动量能。")
    elif amount_ratio20 >= 1.35:
        launch += 12
        evidence.append(f"当日成交额约为20日均额 {amount_ratio20:.1f} 倍，量能开始改善。")
    if ma5 >= ma10 >= ma20:
        launch += 15
        evidence.append("5/10/20日均线短期多头改善。")
    if 2 <= last_change <= 9.5:
        launch += 10
        evidence.append(f"当日涨跌幅 {last_change:.2f}%，有启动表现但未到极端状态。")

    active = {theme for theme in active_themes or []}
    theme_score = 0.0
    if theme_names:
        theme_score += 35
        evidence.append("已识别题材/概念归属：" + "、".join(theme_names[:4]) + "。")
    if active.intersection(theme_names):
        theme_score += 35
        evidence.append("所属题材与当日活跃方向出现共振：" + "、".join(sorted(active.intersection(theme_names))[:3]) + "。")
    if last_change > 0:
        theme_score += 15
    if amount_ratio20 >= 1.3:
        theme_score += 15
    if intraday_proxy == "strong_close":
        theme_score += 10

    risk_penalty = 0.0
    if avg_amount20 < MIN_AVG_AMOUNT:
        risk_penalty += 25
        risks.append("20日平均成交额偏低，流动性不足。")
    if ret10 >= 35:
        risk_penalty += 25
        risks.append(f"近10日涨幅约 {ret10:.1f}%，短期过热。")
    if limit_like_days >= 3:
        risk_penalty += 25
        risks.append("近10日出现多次涨停特征，容易进入过热噪声。")
    if last_change >= 9.6:
        risk_penalty += 15
        risks.append("当日涨幅接近涨停，追踪时需防止高波动。")
    if volume_ratio > 3:
        risk_penalty += 10
        risks.append(f"量比 {volume_ratio:.2f} 偏高，可能存在短线过热。")

    accumulation = _clip(accumulation)
    launch = _clip(launch)
    theme_score = _clip(theme_score)
    risk_penalty = _clip(risk_penalty)
    total = _clip(accumulation * 0.40 + launch * 0.40 + theme_score * 0.20 - risk_penalty)

    if risk_penalty >= 35 and launch >= 60:
        stage = "过热排除"
    elif launch >= 70 and accumulation >= 60:
        stage = "启动确认"
    elif total >= 55 and accumulation >= 50:
        stage = "潜伏观察"
    else:
        stage = "数据不足"
        risks.append(f"未达到观察阈值：潜伏 {accumulation:.0f}，启动 {launch:.0f}，题材 {theme_score:.0f}。")

    metrics.update(
        {
            "range_60d_pct": round(range60, 2),
            "range_120d_pct": round(range120, 2),
            "amount_ratio_20d": round(amount_ratio20, 2),
            "avg_amount_20d": round(avg_amount20, 2),
            "return_10d_pct": round(ret10, 2),
            "ma5": round(ma5, 3),
            "ma10": round(ma10, 3),
            "ma20": round(ma20, 3),
            "ma60": round(ma60, 3),
            "ma120": round(ma120, 3),
            "weekly_bars": len(weekly_bars or []),
        }
    )
    return _candidate(item, trading_day, stage, total, accumulation, launch, theme_score, risk_penalty, evidence, risks, metrics, theme_names, source_ids)


def _candidate(
    item: StockUniverseItem,
    trading_day: date,
    stage: str,
    total: float,
    accumulation: float,
    launch: float,
    theme_score: float,
    risk_penalty: float,
    evidence: list[str],
    risks: list[str],
    metrics: dict[str, object],
    themes: list[str],
    source_ids: Sequence[str] | None = None,
) -> StealthCandidate:
    return StealthCandidate(
        trading_day=trading_day,
        symbol=item.symbol,
        name=item.name,
        stage=stage,  # type: ignore[arg-type]
        total_score=total,
        accumulation_score=accumulation,
        launch_score=launch,
        theme_score=theme_score,
        risk_penalty=risk_penalty,
        evidence=evidence[:8],
        risks=risks[:8],
        metrics=metrics,
        themes=themes[:8],
        source_ids=list(source_ids or ["src-akshare-dev"]),
    )


def run_stealth_scan(
    limit: int | None = None,
    offset: int = 0,
    symbols: list[str] | None = None,
    active_themes: list[str] | None = None,
    progress: ScanProgressCallback | None = None,
    failure: ScanFailureCallback | None = None,
    success: ScanSuccessCallback | None = None,
    include_watchlist: bool = True,
) -> StealthScanRunResponse:
    universe = history_data_provider.stock_universe()
    source_ids = history_data_source_ids(history_data_provider)
    requested = {symbol.upper() for symbol in symbols or []}
    watchlist_symbols = {item.symbol for item in list_watchlist()} if include_watchlist else set()
    selected: list[StockUniverseItem] = []
    seen: set[str] = set()
    if requested:
        target_symbols = requested | watchlist_symbols
        for item in universe:
            if item.symbol in seen or item.is_st or item.symbol not in target_symbols:
                continue
            selected.append(item)
            seen.add(item.symbol)
        for symbol in sorted(target_symbols):
            if symbol not in seen:
                selected.append(StockUniverseItem(symbol=symbol, name=symbol, listed_days=999))
                seen.add(symbol)
    else:
        eligible = [item for item in universe if not item.is_st]
        batch = eligible[offset:]
        for item in batch:
            if item.symbol in seen or item.is_st:
                continue
            if limit is None or len(selected) < limit or item.symbol in watchlist_symbols:
                selected.append(item)
                seen.add(item.symbol)
        for symbol in sorted(watchlist_symbols):
            if symbol not in seen:
                selected.append(StockUniverseItem(symbol=symbol, name=symbol, listed_days=999))
                seen.add(symbol)

    total = len(selected)
    if progress:
        progress({"total": total, "scanned": 0, "saved": 0, "failed": 0, "stages": {}, "message": "股票池已加载，正在保存基础数据。"})

    save_universe_items(selected)
    try:
        market_profiles = fetch_stock_market_profiles([item.symbol for item in selected])
    except HistoryDataUnavailable as exc:
        market_profiles = {}
        if progress:
            progress(
                {
                    "total": total,
                    "scanned": 0,
                    "saved": 0,
                    "failed": 0,
                    "stages": {},
                    "message": f"流通市值/量比画像暂不可用：{exc}",
                }
            )
    memberships = history_data_provider.theme_memberships([item.symbol for item in selected])
    save_theme_memberships(memberships)
    themes_by_symbol: dict[str, list[ThemeMembership]] = {}
    for membership in memberships:
        themes_by_symbol.setdefault(membership.symbol, []).append(membership)

    candidates: list[StealthCandidate] = []
    evaluated: list[StealthCandidate] = []
    scanned = 0
    failed = 0
    stages: Counter[str] = Counter()
    for index, item in enumerate(selected, start=1):
        if progress:
            progress(
                {
                    "total": total,
                    "scanned": scanned,
                    "saved": len(candidates),
                    "failed": failed,
                    "stages": dict(stages),
                    "message": f"准备扫描：{index}/{total}，当前标的 {item.symbol}。",
                }
            )
        try:
            stage = "daily_bars"
            bars = history_data_provider.daily_bars(item.symbol)
            stage = "weekly_bars"
            weekly = history_data_provider.weekly_bars(item.symbol)
        except HistoryDataUnavailable as exc:
            failed += 1
            if failure:
                failure(
                    {
                        "symbol": item.symbol,
                        "name": item.name,
                        "stage": stage,
                        "error": str(exc),
                    }
                )
            if progress and (index == total or index % 10 == 0):
                progress(
                    {
                        "total": total,
                        "scanned": scanned,
                        "saved": len(candidates),
                        "failed": failed,
                        "stages": dict(stages),
                        "message": f"扫描中：{index}/{total}，{item.symbol} 历史数据暂不可用。",
                    }
                )
            continue
        scanned += 1
        if success:
            success(item.symbol)
        save_daily_bars(bars)
        candidate = evaluate_candidate(
            item=item,
            daily_bars=bars,
            weekly_bars=weekly,
            themes=themes_by_symbol.get(item.symbol, []),
            active_themes=active_themes or [],
            source_ids=source_ids,
            market_profile=market_profiles.get(item.symbol),
        )
        evaluated.append(candidate)
        stages[candidate.stage] += 1
        if candidate.stage != "数据不足" and (candidate.total_score >= 45 or candidate.stage == "过热排除"):
            candidates.append(candidate)
        if progress and (index == 1 or index == total or index % 5 == 0):
            progress(
                {
                    "total": total,
                    "scanned": scanned,
                    "saved": len(candidates),
                    "failed": failed,
                    "stages": dict(stages),
                    "message": f"扫描中：{index}/{total}，已保存 {len(candidates)} 个候选。",
                }
            )

    save_scan_results(evaluated)
    trading_day = candidates[0].trading_day if candidates else date.today()
    return StealthScanRunResponse(
        trading_day=trading_day,
        total=total,
        scanned=scanned,
        saved=len(candidates),
        failed=failed,
        stages=dict(stages),
        message="扫描完成；结果仅用于研究筛选和每日观察，不构成投资建议。",
    )
