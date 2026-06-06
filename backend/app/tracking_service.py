from __future__ import annotations

import os
from datetime import date, datetime, timedelta
from typing import Callable

from .data_providers import (
    history_provider_sources,
    information_provider_sources,
    market_data_provider,
    market_provider_sources,
    news_announcement_provider,
)
from .database import get_redis
from .data_freshness import DataFreshnessResult, evaluate_data_freshness
from .job_pipeline import StepOutcome, aggregate_pipeline_status, run_pipeline_step
from .market_provider import CN_TZ
from .models import DailyTrackingReport, InformationDigestItem, InformationSummary, InformationSymbolSummary, JobRun, MarketEvent, MarketSnapshot
from .notification_service import create_freshness_notification, create_pipeline_notification
from .repositories import list_watchlist
from .stealth_repository import list_candidates, list_observations, snapshot_observation_journal
from .stealth_scanner import run_stealth_scan
from .tracking_repository import (
    create_job_run,
    finish_job_run,
    get_daily_tracking_report,
    get_job_run_detail,
    load_data_freshness_inputs,
    list_announcement_items,
    list_job_runs,
    list_job_run_steps,
    list_market_events,
    list_market_snapshots,
    list_news_items,
    save_announcement_items,
    save_daily_tracking_report,
    save_market_events,
    save_market_snapshot,
    save_news_items,
)


JOB_SPECS: dict[str, str] = {
    "preopen_prepare": "07:30 盘前数据准备",
    "preopen_refresh": "09:20 开盘前刷新",
    "intraday_snapshot": "5分钟盘中快照",
    "midday_summary": "11:35 午盘摘要",
    "close_snapshot": "15:05 收盘快照",
    "news_explain": "16:30 公告新闻收集与解释",
    "post_market_replay": "盘后一键复盘闭环",
    "daily_report": "20:30 每日跟踪报告",
    "agent_post_market": "20:40 盘后研究 Agent 工作流",
}

REPORT_SECTION_TITLES = ["市场温度", "指数表现", "板块轮动", "盘中事件", "自选与观察池", "数据质量与缺口"]


def run_tracking_job(job_name: str) -> JobRun:
    normalized = _normalize_job_name(job_name)
    if normalized not in JOB_SPECS:
        raise KeyError(job_name)

    run = create_job_run(normalized, message=f"{JOB_SPECS[normalized]}已启动。")
    lock_key = f"marketlens:job-lock:{normalized}"
    lock = _acquire_lock(lock_key)
    if not lock:
        return finish_job_run(run.id, "failed", message="同名任务正在运行，已跳过本次触发。", error="job locked")

    try:
        if normalized == "post_market_replay":
            scope, message, status = _durable_post_market_replay_job(run.id)
            completed = finish_job_run(run.id, status, message=message, affected_scope=scope)
            create_pipeline_notification(completed)
            create_freshness_notification(run.id, DataFreshnessResult(**scope["data_freshness"]))
            return completed
        handler = _job_handlers()[normalized]
        scope, message = handler()
        return finish_job_run(run.id, "completed", message=message, affected_scope=scope)
    except Exception as exc:
        return finish_job_run(run.id, "failed", message=f"{JOB_SPECS[normalized]}失败。", error=str(exc))
    finally:
        _release_lock(lock_key, lock)


def recent_job_runs(limit: int = 40, job_name: str | None = None) -> list[JobRun]:
    return list_job_runs(limit=limit, job_name=_normalize_job_name(job_name) if job_name else None)


def tracking_job_run_detail(run_id: str):
    return get_job_run_detail(run_id)


def rerun_tracking_job_step(run_id: str, step_name: str):
    detail = get_job_run_detail(run_id)
    if detail is None:
        raise KeyError(run_id)
    if detail.run.job_name != "post_market_replay":
        raise KeyError(step_name)

    known_steps = {
        "close_snapshot",
        "collect_information",
        "stealth_scan",
        "observation_journal",
        "daily_report",
        "agent_post_market",
    }
    if step_name not in known_steps:
        raise KeyError(step_name)
    matching = [step for step in detail.steps if step.step_name == step_name]
    if not matching or matching[-1].status not in {"failed", "degraded", "skipped"}:
        raise ValueError(step_name)

    target_day = datetime.now(CN_TZ).date()
    raw_day = detail.run.affected_scope.get("trading_day")
    if isinstance(raw_day, str):
        target_day = date.fromisoformat(raw_day)

    def handler() -> StepOutcome:
        if step_name == "close_snapshot":
            snapshot = capture_market_snapshot()
            return StepOutcome(result_scope={"snapshot_id": snapshot.id, "events": len(snapshot.event_ids)})
        if step_name == "collect_information":
            news, announcements = collect_news_and_announcements()
            return StepOutcome(result_scope={"news": len(news), "announcements": len(announcements)})
        if step_name == "stealth_scan":
            result = run_stealth_scan(
                limit=_post_market_scan_limit(),
                offset=_post_market_scan_offset(),
                active_themes=[],
                include_watchlist=True,
            )
            return StepOutcome(result_scope={"trading_day": result.trading_day.isoformat(), "saved": result.saved, "failed": result.failed})
        if step_name == "observation_journal":
            return StepOutcome(result_scope={"observation_journal": len(snapshot_observation_journal())})
        if step_name == "daily_report":
            report = build_daily_tracking_report(target_day)
            return StepOutcome(result_scope={"trading_day": report.trading_day.isoformat(), "sections": len(report.sections)})
        agent_scope, _ = _agent_post_market_job()
        return StepOutcome(
            status="degraded" if agent_scope.get("agent_status") == "degraded" else "completed",
            result_scope=agent_scope,
        )

    next_attempt = max(step.attempt for step in matching) + 1
    run_pipeline_step(run_id, step_name, handler, start_attempt=next_attempt)
    status = aggregate_pipeline_status(list_job_run_steps(run_id))
    finish_job_run(
        run_id,
        status,
        message="指定步骤已重跑，运行状态已刷新。",
        affected_scope=detail.run.affected_scope,
    )
    return get_job_run_detail(run_id)


def tracking_daily_report(trading_day: date | None = None) -> DailyTrackingReport:
    day = trading_day or datetime.now(CN_TZ).date()
    stored = get_daily_tracking_report(day)
    snapshots = list_market_snapshots(day)
    events = list_market_events(day)
    news = list_news_items(day)
    announcements = list_announcement_items(day)
    if stored and _has_mvp_report_sections(stored.sections):
        return stored.model_copy(update={"snapshots": snapshots, "events": events, "news": news, "announcements": announcements})
    return build_daily_tracking_report(day)


def build_information_summary(trading_day: date | None = None, symbol: str | None = None) -> InformationSummary:
    day = trading_day or datetime.now(CN_TZ).date()
    news = list_news_items(day, symbol=symbol)
    announcements = list_announcement_items(day, symbol=symbol)
    items = [
        *_digest_items(news, event_type="news"),
        *_digest_items(announcements, event_type="announcement"),
    ]
    items.sort(key=lambda item: item.published_at, reverse=True)
    by_importance = {key: 0 for key in ["critical", "high", "medium", "low"]}
    by_event_type = {"announcement": len(announcements), "news": len(news)}
    symbol_buckets: dict[str, InformationSymbolSummary] = {}

    for item in items:
        by_importance[item.importance] = by_importance.get(item.importance, 0) + 1
        if not item.symbol:
            continue
        bucket = symbol_buckets.setdefault(item.symbol, InformationSymbolSummary(symbol=item.symbol))
        updates = {
            "total": bucket.total + 1,
            "news": bucket.news + (1 if item.event_type == "news" else 0),
            "announcements": bucket.announcements + (1 if item.event_type == "announcement" else 0),
            "high_importance": bucket.high_importance + (1 if item.importance in {"critical", "high"} else 0),
            "latest_title": bucket.latest_title,
            "latest_at": bucket.latest_at,
        }
        if bucket.latest_at is None or item.published_at > bucket.latest_at:
            updates["latest_title"] = item.title
            updates["latest_at"] = item.published_at
        symbol_buckets[item.symbol] = bucket.model_copy(update=updates)

    warnings = []
    if not items:
        warnings.append("新闻/公告源未接入或当日没有写入数据。")
    source_ids = sorted({item.source_id for item in items})
    return InformationSummary(
        trading_day=day,
        total_count=len(items),
        news_count=len(news),
        announcement_count=len(announcements),
        by_importance=by_importance,
        by_event_type=by_event_type,
        by_symbol=sorted(symbol_buckets.values(), key=lambda item: (item.total, item.high_importance), reverse=True)[:10],
        latest_items=items[:12],
        warnings=warnings,
        source_ids=source_ids,
    )


def build_daily_tracking_report(trading_day: date | None = None) -> DailyTrackingReport:
    day = trading_day or datetime.now(CN_TZ).date()
    snapshots = list_market_snapshots(day)
    events = list_market_events(day)
    news = list_news_items(day)
    announcements = list_announcement_items(day)
    latest_snapshot = snapshots[-1] if snapshots else None
    data_warnings = _data_gap_warnings(snapshots, news, announcements)
    headline = "每日市场分析：暂无盘中快照，快照不足，分析置信度低"
    summary = "尚未记录当日 5 分钟快照，请先运行盘中快照或收盘快照任务。"
    if latest_snapshot and len(snapshots) < 2:
        temp = latest_snapshot.market_temperature
        headline = f"每日市场分析：市场温度 {temp.score}，快照不足，分析置信度低"
        summary = (
            f"当日已记录 {len(snapshots)} 个快照、{len(events)} 条事件、"
            f"{len(news)} 条新闻摘要、{len(announcements)} 条公告摘要；快照不足，分析置信度低。"
        )
    elif latest_snapshot:
        temp = latest_snapshot.market_temperature
        headline = f"每日市场分析：市场温度 {temp.score}，上涨 {temp.advancers} 家，下跌 {temp.decliners} 家"
        summary = (
            f"当日已记录 {len(snapshots)} 个快照、{len(events)} 条事件、"
            f"{len(news)} 条新闻摘要、{len(announcements)} 条公告摘要。"
        )
    observations = list_observations()
    candidates = list_candidates(min_score=35, limit=8)
    sections = [
        _market_temperature_section(snapshots, data_warnings),
        _index_performance_section(latest_snapshot),
        _sector_rotation_section(snapshots),
        _intraday_events_section(events, news, announcements),
        _watchlist_observation_section(latest_snapshot, observations, candidates),
        _data_quality_section(snapshots, events, news, announcements, data_warnings),
    ]
    source_ids = _daily_report_source_ids(snapshots, events, news, announcements)
    report = DailyTrackingReport(
        trading_day=day,
        generated_at=datetime.now(CN_TZ),
        headline=headline,
        summary=summary,
        sections=sections,
        source_ids=source_ids,
        snapshots=snapshots,
        events=events,
        news=news,
        announcements=announcements,
    )
    return save_daily_tracking_report(report).model_copy(update={"snapshots": snapshots, "events": events, "news": news, "announcements": announcements})


def _has_mvp_report_sections(sections: list[dict[str, object]]) -> bool:
    return [str(section.get("title") or "") for section in sections] == REPORT_SECTION_TITLES


def _digest_items(items, event_type: str) -> list[InformationDigestItem]:
    return [
        InformationDigestItem(
            id=item.id,
            symbol=item.symbol,
            title=item.title,
            summary=item.summary,
            published_at=item.published_at,
            source_url=item.source_url,
            source_name=item.source_name,
            event_type=event_type,
            importance=item.importance,
            source_id=item.source_id,
        )
        for item in items
    ]


def _configured_source_ids() -> list[str]:
    return [
        source.id
        for source in [
            *market_provider_sources(),
            *history_provider_sources(),
            *information_provider_sources(),
        ]
    ]


def _daily_report_source_ids(snapshots: list[MarketSnapshot], events: list[MarketEvent], news, announcements) -> list[str]:
    return sorted(
        {
            *_configured_source_ids(),
            *(snapshot.source_id for snapshot in snapshots),
            *(source_id for event in events for source_id in event.source_ids),
            *(item.source_id for item in news),
            *(item.source_id for item in announcements),
        }
    )


def _report_section(
    title: str,
    summary: str,
    evidence: list[str] | None = None,
    metrics: dict[str, str | int | float] | None = None,
    warnings: list[str] | None = None,
) -> dict[str, object]:
    section: dict[str, object] = {
        "title": title,
        "summary": summary,
        "evidence": evidence if evidence else ["暂无可引用证据。"],
    }
    if metrics:
        section["metrics"] = metrics
    if warnings:
        section["warnings"] = warnings
    return section


def _data_gap_warnings(snapshots: list[MarketSnapshot], news, announcements) -> list[str]:
    warnings: list[str] = []
    if not snapshots:
        warnings.append("未记录当日盘中快照，快照不足，分析置信度低。")
    elif len(snapshots) < 2:
        warnings.append("当日仅记录 1 个快照，快照不足，分析置信度低。")
    if not news and not announcements:
        warnings.append("新闻/公告源未接入或当日没有写入数据。")
    return warnings


def _market_temperature_section(snapshots: list[MarketSnapshot], data_warnings: list[str]) -> dict[str, object]:
    if not snapshots:
        return _report_section(
            "市场温度",
            "当日尚未形成行情快照，无法计算市场温度变化。",
            evidence=["请先运行盘中快照或收盘快照任务。"],
            metrics={"snapshots": 0},
            warnings=data_warnings,
        )

    first = snapshots[0].market_temperature
    latest = snapshots[-1].market_temperature
    delta = latest.score - first.score
    direction = "走强" if delta > 0 else "转弱" if delta < 0 else "持平"
    return _report_section(
        "市场温度",
        f"最新市场温度 {latest.score}，较首个快照{direction} {abs(delta)} 点；上涨 {latest.advancers} 家，下跌 {latest.decliners} 家。",
        evidence=[
            f"首个快照温度 {first.score}，最新快照温度 {latest.score}",
            f"最新上涨 {latest.advancers} 家，下跌 {latest.decliners} 家",
            f"最新涨停 {latest.limit_up_count} 家，跌停 {latest.limit_down_count} 家",
        ],
        metrics={
            "snapshots": len(snapshots),
            "score": latest.score,
            "score_delta": delta,
            "advancers": latest.advancers,
            "decliners": latest.decliners,
            "limit_up": latest.limit_up_count,
            "limit_down": latest.limit_down_count,
            "turnover_billion": latest.total_turnover_billion,
        },
        warnings=[warning for warning in data_warnings if "快照" in warning],
    )


def _index_performance_section(latest_snapshot: MarketSnapshot | None) -> dict[str, object]:
    if latest_snapshot is None or not latest_snapshot.indexes:
        return _report_section(
            "指数表现",
            "当日没有可用指数快照，指数表现暂不可确认。",
            evidence=["指数数据来自行情快照；当前缺少快照。"],
            metrics={"index_count": 0},
            warnings=["指数数据缺失。"],
        )

    indexes = latest_snapshot.indexes
    strongest = max(indexes, key=lambda item: item.change_pct)
    weakest = min(indexes, key=lambda item: item.change_pct)
    return _report_section(
        "指数表现",
        f"最新快照覆盖 {len(indexes)} 个指数；{strongest.name} 涨跌幅靠前，{weakest.name} 涨跌幅靠后。",
        evidence=[
            f"{item.name} {item.value:.2f}，涨跌幅 {item.change_pct:+.2f}%，成交额 {item.turnover_billion:.0f} 亿"
            for item in indexes[:6]
        ],
        metrics={
            "index_count": len(indexes),
            "strongest_index": strongest.name,
            "strongest_change_pct": strongest.change_pct,
            "weakest_index": weakest.name,
            "weakest_change_pct": weakest.change_pct,
        },
    )


def _sector_rotation_section(snapshots: list[MarketSnapshot]) -> dict[str, object]:
    latest_snapshot = snapshots[-1] if snapshots else None
    if latest_snapshot is None or not latest_snapshot.sectors:
        return _report_section(
            "板块轮动",
            "当日没有可用板块快照，板块轮动暂不可确认。",
            evidence=["板块数据来自行情快照；当前缺少快照。"],
            metrics={"sector_count": 0},
            warnings=["板块数据缺失。"],
        )

    latest_top = latest_snapshot.sectors[0]
    first_top = snapshots[0].sectors[0] if snapshots and snapshots[0].sectors else latest_top
    changed = latest_top.name != first_top.name
    summary = (
        f"最新靠前方向为 {latest_top.name}，涨跌幅 {latest_top.change_pct:+.2f}%。"
        if not changed
        else f"靠前方向由 {first_top.name} 切换至 {latest_top.name}，最新涨跌幅 {latest_top.change_pct:+.2f}%。"
    )
    return _report_section(
        "板块轮动",
        summary,
        evidence=[
            f"{sector.name} 涨跌幅 {sector.change_pct:+.2f}%，成交额 {sector.turnover_billion:.0f} 亿"
            for sector in latest_snapshot.sectors[:6]
        ],
        metrics={
            "sector_count": len(latest_snapshot.sectors),
            "leading_sector": latest_top.name,
            "leading_change_pct": latest_top.change_pct,
            "leading_turnover_billion": latest_top.turnover_billion,
        },
    )


def _intraday_events_section(events: list[MarketEvent], news, announcements) -> dict[str, object]:
    high_events = [event for event in events if event.importance in {"critical", "high"}]
    warnings = []
    if not news and not announcements:
        warnings.append("新闻/公告源未接入或当日没有写入数据。")
    if not events:
        warnings.append("当日没有写入盘中事件，事件回放不足。")
    return _report_section(
        "盘中事件",
        _news_explanation_summary(events, news, announcements),
        evidence=[event.title for event in events[:6]] + [item.title for item in announcements[:3]] + [item.title for item in news[:3]],
        metrics={
            "events": len(events),
            "high_importance_events": len(high_events),
            "news": len(news),
            "announcements": len(announcements),
        },
        warnings=warnings,
    )


def _watchlist_observation_section(latest_snapshot: MarketSnapshot | None, observations, candidates) -> dict[str, object]:
    watchlist = latest_snapshot.watchlist if latest_snapshot else []
    warnings = []
    if not watchlist:
        warnings.append("当日快照未包含自选股数据。")
    if not observations:
        warnings.append("观察池为空或尚未写入最新观察记录。")
    if not candidates:
        warnings.append("尚未运行潜伏挖掘扫描或没有达到阈值的候选结果。")

    watchlist_evidence = [
        f"{item.name} {item.symbol} 最新价 {item.price:.2f}，涨跌幅 {item.change_pct:+.2f}%，量比 {item.volume_ratio:.2f}"
        for item in watchlist[:4]
    ]
    observation_evidence = [
        f"{item.symbol} 观察状态 {item.status}，观察天数 {item.days_observed}"
        for item in observations[:4]
    ]
    candidate_evidence = [
        f"{item.name} {item.symbol}：{item.stage}，总分 {item.total_score:.0f}，依据：{item.evidence[0] if item.evidence else '暂无'}"
        for item in candidates[:4]
    ]
    return _report_section(
        "自选与观察池",
        f"最新快照覆盖 {len(watchlist)} 个自选标的，观察池记录 {len(observations)} 个标的，潜力候选 {len(candidates)} 个。",
        evidence=watchlist_evidence + observation_evidence + candidate_evidence,
        metrics={
            "watchlist": len(watchlist),
            "observations": len(observations),
            "candidates": len(candidates),
            "activation_candidates": sum(1 for item in candidates if item.stage == "启动确认"),
            "watchlist_risk_flags": sum(1 for item in watchlist if item.risk_flags),
        },
        warnings=warnings,
    )


def _data_quality_section(snapshots: list[MarketSnapshot], events: list[MarketEvent], news, announcements, data_warnings: list[str]) -> dict[str, object]:
    latest_snapshot = snapshots[-1] if snapshots else None
    source_ids = _daily_report_source_ids(snapshots, events, news, announcements)
    evidence = [
        f"最新快照时间 {latest_snapshot.captured_at.isoformat()}" if latest_snapshot else "暂无快照时间",
        f"来源标识：{', '.join(source_ids) if source_ids else '暂无'}",
        "当前版本保留开发行情源，生产环境需替换为授权数据源。",
    ]
    if not data_warnings:
        evidence.append("未发现关键数据缺口。")
    return _report_section(
        "数据质量与缺口",
        f"本日报由 {len(snapshots)} 个快照、{len(events)} 条事件、{len(news)} 条新闻摘要、{len(announcements)} 条公告摘要生成。",
        evidence=evidence,
        metrics={
            "snapshots": len(snapshots),
            "events": len(events),
            "news": len(news),
            "announcements": len(announcements),
            "source_count": len(source_ids),
        },
        warnings=data_warnings,
    )


def capture_market_snapshot(interval: str = "5m") -> MarketSnapshot:
    temperature, indexes, sectors, watchlist, base_events, meta = market_data_provider.current_bundle(list_watchlist())
    captured_at = meta.fetched_at
    previous = _latest_snapshot_before(captured_at.date())
    rule_events = detect_intraday_events(previous, temperature, sectors, source_id=meta.source_id, occurred_at=captured_at)
    events = _dedupe_events([*base_events, *rule_events])
    return save_market_snapshot(
        captured_at=captured_at,
        interval=interval,
        provider=meta.provider,
        source_id=meta.source_id,
        license_note=meta.license_note,
        temperature=temperature,
        indexes=indexes,
        sectors=sectors,
        watchlist=watchlist,
        events=events,
    )


def collect_news_and_announcements() -> tuple[list[object], list[object]]:
    symbols = sorted({item.symbol for item in list_watchlist()} | {item.symbol for item in list_observations()})
    news = news_announcement_provider.news(symbols)
    announcements = news_announcement_provider.announcements(symbols)
    save_news_items(news)
    save_announcement_items(announcements)
    return news, announcements


def detect_intraday_events(
    previous: MarketSnapshot | None,
    current_temperature,
    current_sectors,
    *,
    source_id: str,
    occurred_at: datetime,
) -> list[MarketEvent]:
    events: list[MarketEvent] = []
    if previous is not None:
        score_delta = current_temperature.score - previous.market_temperature.score
        if abs(score_delta) >= 15:
            direction = "走强" if score_delta > 0 else "转弱"
            events.append(
                MarketEvent(
                    id=f"rule-breadth-{occurred_at:%Y%m%d%H%M}",
                    occurred_at=occurred_at,
                    type="capital_flow",
                    title=f"市场宽度5分钟内明显{direction}",
                    summary=f"市场温度由 {previous.market_temperature.score} 变为 {current_temperature.score}，变化 {score_delta:+.0f}。",
                    affected_symbols=[],
                    affected_sectors=[],
                    importance="high",
                    fact_basis=[f"前值 {previous.market_temperature.score}", f"现值 {current_temperature.score}"],
                    inference="宽度突变仅表示盘面状态变化，不构成方向预测。",
                    confidence="high",
                    source_ids=[source_id],
                    compliance_label="fact",
                )
            )
        if previous.sectors and current_sectors:
            previous_top = previous.sectors[0]
            current_top = current_sectors[0]
            if current_top.name != previous_top.name or abs(current_top.change_pct - previous_top.change_pct) >= 2:
                events.append(
                    MarketEvent(
                        id=f"rule-sector-{occurred_at:%Y%m%d%H%M}",
                        occurred_at=occurred_at,
                        type="sector_rotation",
                        title="热门方向出现5分钟变化",
                        summary=f"上一快照靠前方向为 {previous_top.name}，当前靠前方向为 {current_top.name}，涨跌幅 {current_top.change_pct:+.2f}%。",
                        affected_symbols=current_top.leading_symbols,
                        affected_sectors=[current_top.name],
                        importance="medium",
                        fact_basis=[f"前一方向 {previous_top.name}", f"当前方向 {current_top.name}"],
                        inference="板块轮动需要结合后续成交额和成分股扩散确认。",
                        confidence="medium",
                        source_ids=[source_id],
                        compliance_label="inference",
                    )
                )
    return events


def _job_handlers() -> dict[str, Callable[[], tuple[dict[str, object], str]]]:
    return {
        "preopen_prepare": _snapshot_job("盘前准备快照已记录。"),
        "preopen_refresh": _snapshot_job("开盘前快照已记录。"),
        "intraday_snapshot": _snapshot_job("5分钟盘中快照已记录。"),
        "midday_summary": _snapshot_job("午盘快照已记录。"),
        "close_snapshot": _close_snapshot_job,
        "news_explain": _news_job,
        "post_market_replay": _post_market_replay_job,
        "daily_report": _daily_report_job,
        "agent_post_market": _agent_post_market_job,
    }


def _snapshot_job(message: str) -> Callable[[], tuple[dict[str, object], str]]:
    def handler() -> tuple[dict[str, object], str]:
        snapshot = capture_market_snapshot()
        return {"snapshot_id": snapshot.id, "events": len(snapshot.event_ids)}, message

    return handler


def _close_snapshot_job() -> tuple[dict[str, object], str]:
    snapshot = capture_market_snapshot()
    journal = snapshot_observation_journal()
    return {"snapshot_id": snapshot.id, "events": len(snapshot.event_ids), "observation_journal": len(journal)}, "收盘快照与观察池日志已记录。"


def _news_job() -> tuple[dict[str, object], str]:
    news, announcements = collect_news_and_announcements()
    return {"news": len(news), "announcements": len(announcements)}, "公告新闻摘要已收集；未找到来源时保留空结果。"


def _daily_report_job() -> tuple[dict[str, object], str]:
    report = build_daily_tracking_report()
    return {"trading_day": report.trading_day.isoformat(), "snapshots": len(report.snapshots), "events": len(report.events)}, "每日跟踪报告已生成。"


def _agent_post_market_job() -> tuple[dict[str, object], str]:
    from .agent_runtime import run_post_market_agent_workflow

    run = run_post_market_agent_workflow(trigger="scheduled_job")
    scope: dict[str, object] = {
        "agent_run_id": run.id,
        "agent_status": run.status,
        "calls_used": run.calls_used,
        "tokens_used": run.tokens_used,
    }
    message = "盘后研究 Agent 工作流已完成。"
    if run.status == "degraded":
        message = "盘后研究 Agent 工作流已降级完成，确定性日报仍可用。"
    return scope, message


def _durable_post_market_replay_job(job_run_id: str) -> tuple[dict[str, object], str, str]:
    state: dict[str, object] = {
        "trading_day": datetime.now(CN_TZ).date(),
        "active_themes": [],
        "report_completed": False,
    }

    def close_snapshot_step() -> StepOutcome:
        snapshot = capture_market_snapshot()
        state["trading_day"] = snapshot.captured_at.date()
        state["active_themes"] = [sector.name for sector in snapshot.sectors[:8]]
        return StepOutcome(result_scope={"snapshot_id": snapshot.id, "events": len(snapshot.event_ids)})

    def information_step() -> StepOutcome:
        news, announcements = collect_news_and_announcements()
        return StepOutcome(result_scope={"news": len(news), "announcements": len(announcements)})

    def scan_step() -> StepOutcome:
        if os.getenv("MARKETLENS_POST_MARKET_ENABLE_SCAN", "1").strip() == "0":
            return StepOutcome(status="skipped", result_scope={"reason": "MARKETLENS_POST_MARKET_ENABLE_SCAN=0"})
        result = run_stealth_scan(
            limit=_post_market_scan_limit(),
            offset=_post_market_scan_offset(),
            active_themes=list(state["active_themes"]),
            include_watchlist=True,
        )
        return StepOutcome(
            result_scope={
                "trading_day": result.trading_day.isoformat(),
                "total": result.total,
                "scanned": result.scanned,
                "saved": result.saved,
                "failed": result.failed,
                "stages": result.stages,
            }
        )

    def journal_step() -> StepOutcome:
        journal = snapshot_observation_journal()
        return StepOutcome(result_scope={"observation_journal": len(journal)})

    def report_step() -> StepOutcome:
        report = build_daily_tracking_report(state["trading_day"])
        state["report_completed"] = True
        return StepOutcome(result_scope={"trading_day": report.trading_day.isoformat(), "sections": len(report.sections)})

    def agent_step() -> StepOutcome:
        if not state["report_completed"]:
            return StepOutcome(status="skipped", result_scope={"reason": "daily_report_failed"})
        agent_scope, _ = _agent_post_market_job()
        status = "degraded" if agent_scope.get("agent_status") == "degraded" else "completed"
        return StepOutcome(status=status, result_scope=agent_scope)

    step_handlers: list[tuple[str, Callable[[], StepOutcome]]] = [
        ("close_snapshot", close_snapshot_step),
        ("collect_information", information_step),
        ("stealth_scan", scan_step),
        ("observation_journal", journal_step),
        ("daily_report", report_step),
        ("agent_post_market", agent_step),
    ]
    latest_steps = [run_pipeline_step(job_run_id, name, handler) for name, handler in step_handlers]
    status = aggregate_pipeline_status(latest_steps)
    freshness = evaluate_data_freshness(state["trading_day"], load_data_freshness_inputs())
    if freshness.status != "fresh" and status == "completed":
        status = "degraded"
    scope: dict[str, object] = {
        "trading_day": state["trading_day"].isoformat(),
        "steps": {step.step_name: step.result_scope for step in latest_steps},
        "data_freshness": freshness.model_dump(mode="json"),
    }
    message = "盘后一键复盘已完成，六个闭环步骤均已记录。"
    if status == "degraded":
        message = "盘后一键复盘已降级完成；日报基于可用数据生成，请查看失败步骤和数据缺口。"
    elif status == "failed":
        message = "盘后一键复盘失败；确定性日报未能生成，请查看步骤详情并重跑。"
    return scope, message, status


def _post_market_replay_job() -> tuple[dict[str, object], str]:
    trading_day = datetime.now(CN_TZ).date()
    snapshot = None
    snapshot_scope: dict[str, object]
    active_themes: list[str] = []
    try:
        snapshot = capture_market_snapshot()
        trading_day = snapshot.captured_at.date()
        active_themes = [sector.name for sector in snapshot.sectors[:8]]
        snapshot_scope = {"status": "completed", "snapshot_id": snapshot.id, "events": len(snapshot.event_ids)}
    except Exception as exc:
        snapshot_scope = {"status": "failed", "error": str(exc)}
    try:
        news, announcements = collect_news_and_announcements()
        information_scope: dict[str, object] = {
            "status": "completed",
            "news": len(news),
            "announcements": len(announcements),
        }
    except Exception as exc:
        news, announcements = [], []
        information_scope = {
            "status": "failed",
            "error": str(exc),
            "news": 0,
            "announcements": 0,
        }
    scan_scope = _run_post_market_scan(active_themes)
    journal = snapshot_observation_journal()
    report = build_daily_tracking_report(trading_day)
    scope: dict[str, object] = {
        "snapshot": snapshot_scope,
        "information": information_scope,
        "news": len(news),
        "announcements": len(announcements),
        "observation_journal": len(journal),
        "report_trading_day": report.trading_day.isoformat(),
        "report_sections": len(report.sections),
        "scan": scan_scope,
    }
    if snapshot is not None:
        scope["snapshot_id"] = snapshot.id
        scope["events"] = len(snapshot.event_ids)
    else:
        scope["events"] = 0
    scan_failed = scan_scope.get("status") == "failed"
    snapshot_failed = snapshot_scope.get("status") == "failed"
    information_failed = information_scope.get("status") == "failed"
    message = "盘后一键复盘已完成；日报、消息摘要、观察日志已刷新。"
    if scan_failed or snapshot_failed or information_failed:
        message = "盘后一键复盘已部分完成；失败步骤已写入运行范围，日报已基于可用数据生成。"
    return scope, message


def _run_post_market_scan(active_themes: list[str]) -> dict[str, object]:
    if os.getenv("MARKETLENS_POST_MARKET_ENABLE_SCAN", "1").strip() == "0":
        return {"status": "skipped", "reason": "MARKETLENS_POST_MARKET_ENABLE_SCAN=0"}
    limit = _post_market_scan_limit()
    offset = _post_market_scan_offset()
    try:
        result = run_stealth_scan(
            limit=limit,
            offset=offset,
            active_themes=active_themes,
            include_watchlist=True,
        )
    except Exception as exc:
        return {
            "status": "failed",
            "error": str(exc),
            "limit": limit or "full",
            "offset": offset,
        }
    return {
        "status": "completed",
        "trading_day": result.trading_day.isoformat(),
        "total": result.total,
        "scanned": result.scanned,
        "saved": result.saved,
        "failed": result.failed,
        "stages": result.stages,
        "limit": limit or "full",
        "offset": offset,
    }


def _post_market_scan_limit() -> int | None:
    raw = os.getenv("MARKETLENS_POST_MARKET_SCAN_LIMIT", "500").strip().lower()
    if raw in {"", "0", "none", "full", "all"}:
        return None
    try:
        return max(1, int(raw))
    except ValueError:
        return 500


def _post_market_scan_offset() -> int:
    try:
        return max(0, int(os.getenv("MARKETLENS_POST_MARKET_SCAN_OFFSET", "0")))
    except ValueError:
        return 0


def _latest_snapshot_before(trading_day: date) -> MarketSnapshot | None:
    snapshots = list_market_snapshots(trading_day)
    return snapshots[-1] if snapshots else None


def _normalize_job_name(job_name: str | None) -> str:
    return (job_name or "").strip().lower().replace("-", "_")


def _dedupe_events(events: list[MarketEvent]) -> list[MarketEvent]:
    result: dict[str, MarketEvent] = {}
    for event in events:
        result[event.id] = event
    return list(result.values())


def _news_explanation_summary(events: list[MarketEvent], news, announcements) -> str:
    if not events:
        return "未找到需要解释的盘中事件。"
    if not news and not announcements:
        return "新闻/公告源未接入或当日没有写入数据；当前解释仅基于行情事件。"
    return "已找到公告/新闻摘要，可结合事件时间线做人工确认。"


def _acquire_lock(lock_key: str) -> str | None:
    token = f"{datetime.now(CN_TZ).timestamp()}"
    try:
        if get_redis().set(lock_key, token, nx=True, ex=60 * 20):
            return token
    except Exception:
        return token
    return None


def _release_lock(lock_key: str, token: str) -> None:
    try:
        redis = get_redis()
        if redis.get(lock_key) == token:
            redis.delete(lock_key)
    except Exception:
        pass
