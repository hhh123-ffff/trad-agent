from __future__ import annotations

from collections import Counter
from datetime import date
from typing import Any, Callable, Sequence

import numpy as np
import pandas as pd

from .data_providers import history_data_provider, history_data_source_ids
from .history_provider import HistoryDataUnavailable
from .models import DailyBar, StealthCandidate, StealthEvidenceItem, StealthScanRunResponse, StockUniverseItem, ThemeMembership
from .repositories import list_watchlist
from .stealth_repository import save_daily_bars, save_scan_results, save_theme_memberships, save_universe_items


MIN_HISTORY_BARS = 120
MIN_AVG_AMOUNT = 50_000_000
ScanProgressCallback = Callable[[dict[str, Any]], None]
ScanFailureCallback = Callable[[dict[str, Any]], None]
ScanSuccessCallback = Callable[[str], None]


def _clip(value: float) -> float:
    if np.isnan(value) or np.isinf(value):
        return 0
    return round(float(max(0, min(100, value))), 2)


def _frame(bars: Sequence[DailyBar]) -> pd.DataFrame:
    return pd.DataFrame([bar.model_dump() for bar in bars]).sort_values("trade_date").reset_index(drop=True)


def evaluate_candidate(
    item: StockUniverseItem,
    daily_bars: Sequence[DailyBar],
    weekly_bars: Sequence[DailyBar] | None = None,
    themes: Sequence[ThemeMembership] | None = None,
    active_themes: Sequence[str] | None = None,
    source_ids: Sequence[str] | None = None,
) -> StealthCandidate:
    trading_day = daily_bars[-1].trade_date if daily_bars else date.today()
    theme_names = sorted({theme.theme_name for theme in themes or []})
    source_refs = list(source_ids or ["src-akshare-dev"])
    evidence: list[str] = []
    risks: list[str] = []
    pattern_tags: list[str] = []
    information_tags: list[str] = []
    metrics: dict[str, Any] = {}

    if item.is_st or "ST" in item.name.upper():
        risk = "ST 或退市风险标的，默认排除。"
        risks.append(risk)
        evidence_breakdown = [
            StealthEvidenceItem(category="风险提示", title="ST 风险排除", detail=risk, weight="high", source_ids=source_refs)
        ]
        return _candidate(
            item,
            trading_day,
            "数据不足",
            0,
            0,
            0,
            0,
            100,
            evidence,
            risks,
            metrics,
            theme_names,
            source_refs,
            horizon_reason="综合观察：存在 ST 或退市风险提示，暂不能归入稳定观察周期。",
            evidence_breakdown=evidence_breakdown,
        )

    if len(daily_bars) < MIN_HISTORY_BARS:
        risk = f"历史日线不足 {MIN_HISTORY_BARS} 根，无法识别长周期结构。"
        risks.append(risk)
        evidence_breakdown = [
            StealthEvidenceItem(category="数据质量", title="历史数据不足", detail=risk, weight="high", source_ids=source_refs)
        ]
        return _candidate(
            item,
            trading_day,
            "数据不足",
            0,
            0,
            0,
            0,
            80,
            evidence,
            risks,
            metrics,
            theme_names,
            source_refs,
            horizon_reason="综合观察：历史 K 线不足，暂不能稳定判断短线或中长线结构。",
            evidence_breakdown=evidence_breakdown,
        )

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
    ret10 = float((last_close / max(float(close.iloc[-11]), 0.01) - 1) * 100) if len(close) > 11 else 0
    limit_like_days = int((change_pct.tail(10) >= 9.6).sum())

    accumulation = 0.0
    if range120 <= 35:
        accumulation += 22
        pattern_tags.append("平台收敛")
        evidence.append(f"120日区间振幅约 {range120:.1f}%，长周期波动收敛。")
    if range60 <= 25:
        accumulation += 18
        pattern_tags.append("平台收敛")
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
        pattern_tags.append("均线修复")
        evidence.append("收盘价重新站在60日均线之上。")
    if last_close >= ma120:
        accumulation += 5
        pattern_tags.append("均线修复")

    launch = 0.0
    if last_close >= prior60_high * 0.995:
        launch += 28
        pattern_tags.append("平台突破")
        evidence.append("收盘价接近或突破60日平台高点。")
    if last_close >= prior120_high * 0.995:
        launch += 18
        pattern_tags.append("平台突破")
        evidence.append("收盘价接近或突破120日压力区。")
    if amount_ratio20 >= 1.8:
        launch += 24
        pattern_tags.append("放量突破")
        evidence.append(f"当日成交额约为20日均额 {amount_ratio20:.1f} 倍，出现启动量能。")
    elif amount_ratio20 >= 1.35:
        launch += 12
        pattern_tags.append("放量突破")
        evidence.append(f"当日成交额约为20日均额 {amount_ratio20:.1f} 倍，量能开始改善。")
    if ma5 >= ma10 >= ma20:
        launch += 15
        pattern_tags.append("短均多头")
        evidence.append("5/10/20日均线短期多头改善。")
    if 2 <= last_change <= 9.5:
        launch += 10
        pattern_tags.append("强势阳线")
        evidence.append(f"当日涨跌幅 {last_change:.2f}%，有启动表现但未到极端状态。")

    active = {theme for theme in active_themes or []}
    theme_score = 0.0
    if theme_names:
        theme_score += 35
        information_tags.append("题材归属")
        evidence.append("已识别题材/概念归属：" + "、".join(theme_names[:4]) + "。")
    if active.intersection(theme_names):
        theme_score += 35
        information_tags.extend(["题材共振", "信息共振"])
        evidence.append("所属题材与当日活跃方向出现共振：" + "、".join(sorted(active.intersection(theme_names))[:3]) + "。")
    if last_change > 0:
        theme_score += 15
    if amount_ratio20 >= 1.3:
        theme_score += 15

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

    accumulation = _clip(accumulation)
    launch = _clip(launch)
    theme_score = _clip(theme_score)
    risk_penalty = _clip(risk_penalty)
    total = _clip(accumulation * 0.45 + launch * 0.30 + theme_score * 0.25 - risk_penalty)

    if risk_penalty >= 35 and launch >= 60:
        stage = "过热排除"
    elif launch >= 70 and accumulation >= 45 and theme_score >= 40:
        stage = "启动确认"
    elif accumulation >= 65 and theme_score >= 50:
        stage = "潜伏观察"
    else:
        stage = "数据不足"
        risks.append(f"未达到观察阈值：潜伏 {accumulation:.0f}，启动 {launch:.0f}，题材 {theme_score:.0f}。")

    pattern_tags = _unique(pattern_tags)
    information_tags = _unique(information_tags)
    strategy_horizon = _strategy_horizon(
        accumulation=accumulation,
        launch=launch,
        risk_penalty=risk_penalty,
        amount_ratio20=amount_ratio20,
        last_change=last_change,
        pattern_tags=pattern_tags,
        information_tags=information_tags,
    )
    horizon_reason = _horizon_reason(
        strategy_horizon=strategy_horizon,
        accumulation=accumulation,
        launch=launch,
        theme_score=theme_score,
        risk_penalty=risk_penalty,
        pattern_tags=pattern_tags,
        information_tags=information_tags,
    )
    evidence_breakdown = _build_evidence_breakdown(
        pattern_tags=pattern_tags,
        information_tags=information_tags,
        theme_names=theme_names,
        active_themes=sorted(active.intersection(theme_names)),
        risks=risks,
        source_ids=source_refs,
        range60=range60,
        range120=range120,
        amount_ratio20=amount_ratio20,
        last_change=last_change,
        risk_penalty=risk_penalty,
        stage=stage,
    )

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
            "strategy_horizon": strategy_horizon,
            "horizon_reason": horizon_reason,
            "evidence_breakdown": [item.model_dump() for item in evidence_breakdown],
            "pattern_tags": pattern_tags,
            "information_tags": information_tags,
        }
    )
    return _candidate(
        item,
        trading_day,
        stage,
        total,
        accumulation,
        launch,
        theme_score,
        risk_penalty,
        evidence,
        risks,
        metrics,
        theme_names,
        source_refs,
        strategy_horizon=strategy_horizon,
        horizon_reason=horizon_reason,
        evidence_breakdown=evidence_breakdown,
        pattern_tags=pattern_tags,
        information_tags=information_tags,
    )


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
    strategy_horizon: str = "综合观察",
    horizon_reason: str = "",
    evidence_breakdown: list[StealthEvidenceItem] | None = None,
    pattern_tags: list[str] | None = None,
    information_tags: list[str] | None = None,
) -> StealthCandidate:
    evidence_items = list(evidence_breakdown or [])[:12]
    candidate_metrics = dict(metrics)
    candidate_metrics.setdefault("strategy_horizon", strategy_horizon)
    candidate_metrics.setdefault("horizon_reason", horizon_reason)
    candidate_metrics.setdefault("evidence_breakdown", [item.model_dump() for item in evidence_items])
    candidate_metrics.setdefault("pattern_tags", list(pattern_tags or [])[:8])
    candidate_metrics.setdefault("information_tags", list(information_tags or [])[:8])
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
        metrics=candidate_metrics,
        themes=themes[:8],
        strategy_horizon=strategy_horizon,  # type: ignore[arg-type]
        horizon_reason=horizon_reason,
        evidence_breakdown=evidence_items,
        pattern_tags=list(pattern_tags or [])[:8],
        information_tags=list(information_tags or [])[:8],
        source_ids=list(source_ids or ["src-akshare-dev"]),
    )


def _unique(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result


def _strategy_horizon(
    *,
    accumulation: float,
    launch: float,
    risk_penalty: float,
    amount_ratio20: float,
    last_change: float,
    pattern_tags: list[str],
    information_tags: list[str],
) -> str:
    if risk_penalty >= 35 and launch >= 60:
        return "短线"
    if launch >= 65 and amount_ratio20 >= 1.35 and ("平台突破" in pattern_tags or "强势阳线" in pattern_tags):
        return "短线"
    if last_change >= 2 and "信息共振" in information_tags and "放量突破" in pattern_tags:
        return "短线"
    if accumulation >= 65 and ("平台收敛" in pattern_tags or "均线修复" in pattern_tags):
        return "中长线"
    return "综合观察"


def _horizon_reason(
    *,
    strategy_horizon: str,
    accumulation: float,
    launch: float,
    theme_score: float,
    risk_penalty: float,
    pattern_tags: list[str],
    information_tags: list[str],
) -> str:
    if strategy_horizon == "短线":
        triggers = [tag for tag in ["平台突破", "放量突破", "强势阳线", "信息共振"] if tag in pattern_tags or tag in information_tags]
        trigger_text = "、".join(triggers[:3]) or "启动信号"
        return f"短线：启动分 {launch:.0f}，{trigger_text} 更突出，当前更偏短周期复盘观察。"
    if strategy_horizon == "中长线":
        structure = [tag for tag in ["平台收敛", "均线修复", "题材共振"] if tag in pattern_tags or tag in information_tags]
        structure_text = "、".join(structure[:3]) or "潜伏结构"
        return f"中长线：潜伏分 {accumulation:.0f}，{structure_text} 更突出，当前更偏中长周期观察。"
    if risk_penalty >= 35:
        return f"综合观察：风险扣分 {risk_penalty:.0f} 偏高，短线和中长线证据需要继续复盘确认。"
    return f"综合观察：潜伏 {accumulation:.0f} / 启动 {launch:.0f} / 题材 {theme_score:.0f} 尚未形成稳定归类。"


def _build_evidence_breakdown(
    *,
    pattern_tags: list[str],
    information_tags: list[str],
    theme_names: list[str],
    active_themes: list[str],
    risks: list[str],
    source_ids: list[str],
    range60: float,
    range120: float,
    amount_ratio20: float,
    last_change: float,
    risk_penalty: float,
    stage: str,
) -> list[StealthEvidenceItem]:
    items: list[StealthEvidenceItem] = []

    def add(category: str, title: str, detail: str, weight: str = "medium") -> None:
        items.append(
            StealthEvidenceItem(
                category=category,  # type: ignore[arg-type]
                title=title,
                detail=detail,
                weight=weight,  # type: ignore[arg-type]
                source_ids=source_ids,
            )
        )

    if "平台收敛" in pattern_tags:
        add("量价图形", "平台收敛", f"60日区间振幅约 {range60:.1f}%，120日区间振幅约 {range120:.1f}%，长周期波动收敛。", "high")
    if "均线修复" in pattern_tags:
        add("量价图形", "均线修复", "收盘价重新站上中长期均线，结构从弱修复到可观察区。", "medium")
    if "平台突破" in pattern_tags:
        add("量价图形", "平台突破", "收盘价接近或突破近期平台高点，启动信号增强。", "high")
    if "放量突破" in pattern_tags:
        add("量价图形", "放量突破", f"当日成交额约为20日均额 {amount_ratio20:.1f} 倍，量能明显改善。", "high")
    if "短均多头" in pattern_tags:
        add("量价图形", "短均多头", "5/10/20日均线短期排列改善，价格结构转强。", "medium")
    if "强势阳线" in pattern_tags:
        add("量价图形", "强势阳线", f"当日涨跌幅 {last_change:.2f}%，有启动表现但未到极端状态。", "medium")

    if "题材归属" in information_tags and theme_names:
        add("题材信息", "题材归属", "已识别题材/概念归属：" + "、".join(theme_names[:4]) + "。", "medium")
    if "题材共振" in information_tags and active_themes:
        add("题材信息", "题材共振", "所属题材与当日活跃方向共振：" + "、".join(active_themes[:3]) + "。", "high")
    if "信息共振" in information_tags:
        add("题材信息", "信息共振", "题材活跃方向与量价改善同时出现，需要结合后续信息继续复盘。", "medium")

    for risk in risks[:4]:
        if "未达到观察阈值" in risk or "历史日线不足" in risk:
            add("数据质量", "候选证据不足", risk, "low")
        else:
            add("风险提示", "风险排除项", risk, "high" if risk_penalty >= 35 else "medium")

    if not items:
        title = "候选证据不足" if stage == "数据不足" else "证据待补充"
        add("数据质量", title, "当前结构化证据不足，先保留文本证据并等待下一轮扫描补充。", "low")

    return items[:12]


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
