from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import date, datetime
from threading import Lock
from time import monotonic

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .agent_repository import apply_agent_action, get_agent_run_detail, list_agent_actions, list_agent_runs, set_agent_action_status
from .agent_runtime import agent_usage_summary, run_research_query_agent
from .agent_status import build_agent_statuses
from .compliance import blocked_answer, check_text
from .data_providers import (
    data_source_statuses,
    history_data_provider,
    history_provider_sources,
    information_provider_sources,
    market_data_provider,
    market_provider_sources,
    provider_quote_rows,
    source_ref_for_id,
)
from .database import check_postgres, check_redis
from .history_provider import HistoryDataUnavailable
from .llm_client import OpenAICompatibleClient
from .market_provider import (
    DISCLAIMER,
    build_live_preopen,
    build_live_replay,
    live_source,
)
from .market_scope import is_mainboard_symbol
from .models import (
    AgentAction,
    AgentRun,
    AgentRunDetail,
    AgentStatusResponse,
    AgentUsageSummary,
    AnnouncementItem,
    AppNotification,
    AssistantAnswer,
    AssistantQuery,
    ComplianceCheck,
    Confidence,
    DailyTrackingReport,
    DashboardResponse,
    InformationSummary,
    JobRun,
    JobRunDetail,
    MarketEvent,
    MarketSnapshot,
    NewsItem,
    PreopenBrief,
    ReplayReport,
    ObservationItem,
    ObservationJournalEntry,
    ObservationRequest,
    ObservationSummary,
    StockProfile,
    StealthCandidate,
    StealthCandidateDetail,
    StealthScanMonitor,
    StealthScanFailure,
    StealthScanRunRequest,
    StealthScanTask,
    StrategyBacktestDetail,
    StrategyBacktestFunnel,
    StrategyBacktestRequest,
    StrategyBacktestRun,
    StrategyLiveOutcomeSummary,
    StrategySignalOutcome,
    WatchlistItemCreate,
    WatchlistItemUpdate,
    WatchlistStock,
)
from .repositories import (
    delete_watchlist_item,
    ensure_storage,
    get_watchlist_item,
    list_assistant_queries,
    list_watchlist,
    save_assistant_query,
    update_watchlist_item,
    upsert_watchlist_item,
    watchlist_count_cache,
)
from .stealth_repository import (
    build_observation_summary,
    delete_observation,
    build_scan_monitor,
    get_candidate,
    list_candidates,
    list_daily_bars,
    list_strategy_diagnostics,
    list_scan_failures,
    list_observations,
    list_observation_journal,
    get_scan_task,
    latest_scan_task,
    mark_task_scan_failures_resolved,
    mark_unfinished_scan_tasks_failed,
    observe_symbol,
    snapshot_observation_journal,
)
from .stealth_tasks import enqueue_failed_symbols_retry, enqueue_stealth_scan_task
from .strategy_backtest import build_live_outcome_summary
from .strategy_backtest_repository import (
    get_backtest_detail,
    get_backtest_funnel,
    get_backtest_run,
    get_latest_backtest_run,
    list_signal_outcomes,
    mark_unfinished_backtests_failed,
)
from .strategy_backtest_tasks import enqueue_strategy_backtest
from .tracking_repository import list_announcement_items, list_market_events, list_market_snapshots, list_news_items
from .tracking_scheduler import start_scheduler, stop_scheduler
from .tracking_repository import list_app_notifications, mark_app_notification_read
from .tracking_service import (
    JOB_SPECS,
    build_information_summary,
    recent_job_runs,
    rerun_tracking_job_step,
    run_tracking_job,
    tracking_daily_report,
    tracking_job_run_detail,
)


MARKET_CACHE_TTL_SECONDS = 20
MARKET_STALE_TTL_SECONDS = 90
_market_cache: tuple[object, ...] | None = None
_market_cache_at = 0.0
_market_cache_lock = Lock()


@asynccontextmanager
async def lifespan(_: FastAPI):
    ensure_storage()
    mark_unfinished_scan_tasks_failed()
    mark_unfinished_backtests_failed()
    start_scheduler()
    yield
    stop_scheduler()


app = FastAPI(
    title="MarketLens API",
    version="0.2.0",
    description="A-share pre-open reference and post-market replay SaaS API.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:3000",
        "http://localhost:3000",
        "http://127.0.0.1:3001",
        "http://localhost:3001",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def market_unavailable(exc: Exception) -> HTTPException:
    return HTTPException(status_code=503, detail=f"真实行情源暂不可用：{exc}")


def history_unavailable(exc: Exception) -> HTTPException:
    return HTTPException(status_code=503, detail=f"历史数据源暂不可用：{exc}")


def current_market():
    global _market_cache, _market_cache_at
    now = monotonic()
    if _market_cache is not None and now - _market_cache_at <= MARKET_CACHE_TTL_SECONDS:
        return _market_cache

    with _market_cache_lock:
        now = monotonic()
        if _market_cache is not None and now - _market_cache_at <= MARKET_CACHE_TTL_SECONDS:
            return _market_cache
        try:
            temperature, indexes, sectors, watchlist, events, meta = market_data_provider.current_bundle(list_watchlist())
            _market_cache = (temperature, indexes, sectors, watchlist, events, source_ref_for_id(meta.source_id))
            _market_cache_at = monotonic()
            return _market_cache
        except Exception as exc:
            if _market_cache is not None and now - _market_cache_at <= MARKET_STALE_TTL_SECONDS:
                return _market_cache
            raise market_unavailable(exc) from exc


def invalidate_market_cache() -> None:
    global _market_cache, _market_cache_at
    with _market_cache_lock:
        _market_cache = None
        _market_cache_at = 0.0


def quote_float(value: object, default: float = 0) -> float:
    try:
        if value in (None, "-", ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def fetch_quote_rows(symbols: list[str]) -> dict[str, dict[str, object]]:
    return provider_quote_rows(symbols)


def parse_trading_day(raw: str | None) -> date:
    if not raw:
        return datetime.now().date()
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=422, detail="date must be YYYY-MM-DD") from None


@app.get("/health")
def health() -> dict[str, object]:
    postgres_ok = check_postgres()
    redis_ok = check_redis()
    return {
        "status": "ok" if postgres_ok and redis_ok else "degraded",
        "service": "marketlens-api",
        "postgres": postgres_ok,
        "redis": redis_ok,
    }


@app.get("/api/dashboard", response_model=DashboardResponse)
def dashboard() -> DashboardResponse:
    temperature, indexes, sectors, watchlist, events, source = current_market()
    return DashboardResponse(
        temperature=temperature,
        indexes=indexes,
        sectors=sectors,
        watchlist=watchlist,
        events=events,
        sources=[source],
        disclaimer=DISCLAIMER,
    )


@app.get("/api/preopen", response_model=PreopenBrief)
def preopen() -> PreopenBrief:
    temperature, _, sectors, watchlist, _, source = current_market()
    return build_live_preopen(temperature, sectors, watchlist, source)


@app.get("/api/radar/events", response_model=list[MarketEvent])
def radar_events(importance: str | None = None) -> list[MarketEvent]:
    _, _, _, _, events, _ = current_market()
    if importance is None:
        return events
    return [event for event in events if event.importance == importance]


@app.get("/api/replay", response_model=ReplayReport)
def replay() -> ReplayReport:
    temperature, _, sectors, _, events, source = current_market()
    return build_live_replay(events, temperature, sectors, source)


@app.get("/api/watchlist")
def watchlist() -> dict[str, object]:
    _, _, _, items, _, _ = current_market()
    cached_count = watchlist_count_cache()
    return {
        "items": items,
        "limit": 50,
        "tier": "pro",
        "cached_count": int(cached_count) if cached_count is not None else len(items),
        "disclaimer": DISCLAIMER,
    }


@app.post("/api/watchlist", response_model=WatchlistStock)
def create_watchlist_item(payload: WatchlistItemCreate) -> WatchlistStock:
    symbol = payload.symbol.upper()
    try:
        quote = fetch_quote_rows([symbol]).get(symbol)
    except Exception as exc:
        raise market_unavailable(exc) from exc
    if not quote:
        raise HTTPException(status_code=404, detail="未从真实行情源找到该 A 股代码。")
    latest = quote_float(quote.get("f2") or quote.get("latest") or quote.get("close") or quote.get("new"))
    change_pct = quote_float(quote.get("f3") or quote.get("changeRatio") or quote.get("change_pct"))
    volume_ratio = quote_float(quote.get("f10") or quote.get("volumeRatio") or quote.get("vol_ratio"), 1)
    source_id = str(quote.get("_source_id") or quote.get("source_id") or getattr(market_data_provider, "source_id", "src-eastmoney-live"))
    real_payload = payload.model_copy(
        update={
            "symbol": symbol,
            "name": str(quote.get("f14") or quote.get("name") or quote.get("secName") or payload.name),
            "price": latest,
            "change_pct": change_pct,
            "volume_ratio": volume_ratio,
            "latest_event": f"实时行情：{latest:.2f}，涨跌幅 {change_pct:+.2f}%。",
            "source_id": source_id,
        }
    )
    created = upsert_watchlist_item(real_payload)
    invalidate_market_cache()
    return created


@app.patch("/api/watchlist/{symbol}", response_model=WatchlistStock)
def patch_watchlist_item(symbol: str, payload: WatchlistItemUpdate) -> WatchlistStock:
    try:
        updated = update_watchlist_item(symbol, payload)
        invalidate_market_cache()
        return updated
    except KeyError:
        raise HTTPException(status_code=404, detail="Watchlist item not found.") from None


@app.delete("/api/watchlist/{symbol}")
def remove_watchlist_item(symbol: str) -> dict[str, object]:
    deleted = delete_watchlist_item(symbol)
    if not deleted:
        raise HTTPException(status_code=404, detail="Watchlist item not found.")
    invalidate_market_cache()
    return {"deleted": True, "symbol": symbol.upper()}


@app.get("/api/stocks/{symbol}", response_model=StockProfile)
def stock_profile(symbol: str) -> StockProfile:
    normalized = symbol.upper()
    stock = get_watchlist_item(normalized)
    if stock is None:
        raise HTTPException(status_code=404, detail="Stock is not in the watchlist.")

    _, _, _, watchlist_items, events, source = current_market()
    live_stock = next((item for item in watchlist_items if item.symbol == normalized), stock)
    recent_events = [event for event in events if normalized in event.affected_symbols]
    fundamentals = {
        "notice": "当前未接入授权财务源，暂不展示财务指标。",
    }
    returns = {"1d": live_stock.change_pct}
    return StockProfile(
        symbol=live_stock.symbol,
        name=live_stock.name,
        sector=live_stock.tags[0] if live_stock.tags else "未分组",
        price=live_stock.price,
        change_pct=live_stock.change_pct,
        returns=returns,
        fundamentals=fundamentals,
        themes=live_stock.tags,
        risk_flags=live_stock.risk_flags,
        recent_events=recent_events,
        sources=[source],
        disclaimer=DISCLAIMER,
    )


@app.get("/api/stealth/candidates", response_model=list[StealthCandidate])
def stealth_candidates(
    stage: str | None = None,
    min_score: float = 0,
    limit: int = 50,
    suppress_repeats: bool = True,
    repeat_days: int = 3,
) -> list[StealthCandidate]:
    return list_candidates(
        stage=stage,
        min_score=min_score,
        limit=min(max(limit, 1), 200),
        suppress_repeats=suppress_repeats,
        repeat_days=min(max(repeat_days, 2), 10),
    )


@app.get("/api/stealth/diagnostics", response_model=list[StealthCandidate])
def stealth_diagnostics(min_score: float = 20, limit: int = 30) -> list[StealthCandidate]:
    return list_strategy_diagnostics(min_score=min_score, limit=min(max(limit, 1), 200))


@app.get("/api/stealth/candidates/{symbol}", response_model=StealthCandidateDetail)
def stealth_candidate_detail(symbol: str) -> StealthCandidateDetail:
    candidate = get_candidate(symbol)
    if candidate is None:
        raise HTTPException(status_code=404, detail="Stealth candidate not found.")
    bars = list_daily_bars(candidate.symbol)
    try:
        weekly_bars = history_data_provider.weekly_bars(candidate.symbol, weeks=80)
    except HistoryDataUnavailable:
        weekly_bars = []
    return StealthCandidateDetail(
        candidate=candidate,
        bars=bars,
        weekly_bars=weekly_bars,
        source_refs=history_provider_sources(),
    )


@app.post("/api/stealth/scan/run", response_model=StealthScanTask)
def stealth_scan_run(payload: StealthScanRunRequest | None = None) -> StealthScanTask:
    request = payload or StealthScanRunRequest()
    if any(not is_mainboard_symbol(symbol) for symbol in request.symbols):
        raise HTTPException(status_code=422, detail="策略范围仅允许沪深主板、非 ST 标的。")
    return enqueue_stealth_scan_task(request, _active_themes())


def _active_themes() -> list[str]:
    try:
        _, _, sectors, _, _, _ = current_market()
        return [sector.name for sector in sectors]
    except HTTPException:
        return []


@app.get("/api/stealth/scan/monitor", response_model=StealthScanMonitor)
def stealth_scan_monitor() -> StealthScanMonitor:
    return build_scan_monitor()


@app.get("/api/stealth/scan/tasks/latest", response_model=StealthScanTask | None)
def stealth_latest_scan_task() -> StealthScanTask | None:
    return latest_scan_task()


@app.get("/api/stealth/scan/tasks/{task_id}", response_model=StealthScanTask)
def stealth_scan_task(task_id: str) -> StealthScanTask:
    task = get_scan_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Scan task not found.")
    return task


@app.get("/api/stealth/scan/tasks/{task_id}/failures", response_model=list[StealthScanFailure])
def stealth_scan_task_failures(task_id: str, unresolved_only: bool = False) -> list[StealthScanFailure]:
    task = get_scan_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Scan task not found.")
    return list_scan_failures(task_id, unresolved_only=unresolved_only)


@app.post("/api/stealth/scan/tasks/{task_id}/retry-failures", response_model=StealthScanTask)
def stealth_retry_scan_task_failures(task_id: str) -> StealthScanTask:
    task = get_scan_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Scan task not found.")
    retry_task = enqueue_failed_symbols_retry(task_id, _active_themes())
    if retry_task is None:
        raise HTTPException(status_code=409, detail="No unresolved failures to retry.")
    return retry_task


@app.post("/api/strategy/backtests/run", response_model=StrategyBacktestRun)
def strategy_backtest_run(payload: StrategyBacktestRequest) -> StrategyBacktestRun:
    if payload.start_date and payload.end_date and payload.start_date > payload.end_date:
        raise HTTPException(status_code=422, detail="start_date must not be after end_date.")
    if any(not is_mainboard_symbol(symbol) for symbol in payload.symbols):
        raise HTTPException(status_code=422, detail="策略范围仅允许沪深主板、非 ST 标的。")
    return enqueue_strategy_backtest(payload)


@app.get("/api/strategy/backtests/latest", response_model=StrategyBacktestRun)
def strategy_latest_backtest() -> StrategyBacktestRun:
    run = get_latest_backtest_run()
    if run is None:
        raise HTTPException(status_code=404, detail="No strategy backtest has been run.")
    return run


@app.get("/api/strategy/backtests/{run_id}", response_model=StrategyBacktestDetail)
def strategy_backtest_detail(run_id: str) -> StrategyBacktestDetail:
    detail = get_backtest_detail(run_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Strategy backtest not found.")
    return detail


@app.get("/api/strategy/backtests/{run_id}/signals", response_model=list[StrategySignalOutcome])
def strategy_backtest_signals(
    run_id: str,
    stage: str | None = None,
    primary_only: bool = False,
    limit: int = 100,
    offset: int = 0,
) -> list[StrategySignalOutcome]:
    if get_backtest_run(run_id) is None:
        raise HTTPException(status_code=404, detail="Strategy backtest not found.")
    return list_signal_outcomes(
        backtest_run_id=run_id,
        origin="replay",
        stage=stage,
        primary_only=primary_only,
        limit=min(max(limit, 1), 500),
        offset=max(offset, 0),
    )


@app.get("/api/strategy/backtests/{run_id}/funnel", response_model=StrategyBacktestFunnel)
def strategy_backtest_funnel(run_id: str) -> StrategyBacktestFunnel:
    funnel = get_backtest_funnel(run_id)
    if funnel is None:
        raise HTTPException(status_code=404, detail="Strategy backtest funnel not found.")
    return funnel


@app.get("/api/strategy/live-outcomes", response_model=StrategyLiveOutcomeSummary)
def strategy_live_outcomes() -> StrategyLiveOutcomeSummary:
    return build_live_outcome_summary()


@app.post("/api/stealth/scan/tasks/{task_id}/resolve-failures")
def stealth_resolve_scan_task_failures(task_id: str) -> dict[str, object]:
    task = get_scan_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Scan task not found.")
    resolved = mark_task_scan_failures_resolved(task_id)
    return {"task_id": task_id, "resolved": resolved}


@app.post("/api/stealth/observe/{symbol}", response_model=ObservationItem)
def stealth_observe(symbol: str, payload: ObservationRequest | None = None) -> ObservationItem:
    request = payload or ObservationRequest()
    try:
        return observe_symbol(
            symbol,
            reason=request.reason,
            note=request.note,
            invalidation_rule=request.invalidation_rule,
            next_focus=request.next_focus,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


@app.patch("/api/stealth/observe/{symbol}", response_model=ObservationItem)
def stealth_update_observation(symbol: str, payload: ObservationRequest) -> ObservationItem:
    try:
        return observe_symbol(
            symbol,
            reason=payload.reason,
            note=payload.note,
            invalidation_rule=payload.invalidation_rule,
            next_focus=payload.next_focus,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


@app.delete("/api/stealth/observe/{symbol}")
def stealth_unobserve(symbol: str) -> dict[str, object]:
    deleted = delete_observation(symbol)
    if not deleted:
        raise HTTPException(status_code=404, detail="Observation item not found.")
    return {"deleted": True, "symbol": symbol.upper()}


@app.get("/api/stealth/observations/summary", response_model=ObservationSummary)
def stealth_observation_summary() -> ObservationSummary:
    return build_observation_summary()


@app.post("/api/stealth/observations/scan", response_model=StealthScanTask)
def stealth_observation_scan() -> StealthScanTask:
    observations = list_observations()
    symbols = sorted({item.symbol for item in observations})
    if not symbols:
        raise HTTPException(status_code=409, detail="Observation pool is empty.")
    request = StealthScanRunRequest(symbols=symbols)
    return enqueue_stealth_scan_task(request, _active_themes(), include_watchlist=False)


@app.get("/api/stealth/observations/journal", response_model=list[ObservationJournalEntry])
def stealth_observation_journal(symbol: str | None = None, limit: int = 80) -> list[ObservationJournalEntry]:
    return list_observation_journal(symbol=symbol, limit=min(max(limit, 1), 300))


@app.post("/api/stealth/observations/journal/snapshot", response_model=list[ObservationJournalEntry])
def stealth_observation_journal_snapshot() -> list[ObservationJournalEntry]:
    return snapshot_observation_journal()


@app.get("/api/stealth/observations", response_model=list[ObservationItem])
def stealth_observations() -> list[ObservationItem]:
    return list_observations()


@app.get("/api/tracking/daily", response_model=DailyTrackingReport)
def tracking_daily(date: str | None = None) -> DailyTrackingReport:
    return tracking_daily_report(parse_trading_day(date))


@app.get("/api/tracking/events", response_model=list[MarketEvent])
def tracking_events(date: str | None = None, symbol: str | None = None, type: str | None = None) -> list[MarketEvent]:
    return list_market_events(parse_trading_day(date), symbol=symbol, event_type=type)


@app.get("/api/tracking/snapshots", response_model=list[MarketSnapshot])
def tracking_snapshots(date: str | None = None, interval: str = "5m") -> list[MarketSnapshot]:
    return list_market_snapshots(parse_trading_day(date), interval=interval)


@app.get("/api/tracking/information-summary", response_model=InformationSummary)
def tracking_information_summary(date: str | None = None, symbol: str | None = None) -> InformationSummary:
    return build_information_summary(parse_trading_day(date), symbol=symbol)


@app.get("/api/news", response_model=list[NewsItem])
def tracking_news(date: str | None = None, symbol: str | None = None) -> list[NewsItem]:
    return list_news_items(parse_trading_day(date), symbol=symbol)


@app.get("/api/announcements", response_model=list[AnnouncementItem])
def tracking_announcements(date: str | None = None, symbol: str | None = None) -> list[AnnouncementItem]:
    return list_announcement_items(parse_trading_day(date), symbol=symbol)


@app.post("/api/admin/jobs/run/{job_name}", response_model=JobRun)
def run_admin_job(job_name: str) -> JobRun:
    try:
        return run_tracking_job(job_name)
    except KeyError:
        raise HTTPException(status_code=404, detail="Unknown tracking job.") from None


@app.get("/api/admin/jobs/runs", response_model=list[JobRun])
def admin_job_runs(limit: int = 40, job_name: str | None = None) -> list[JobRun]:
    return recent_job_runs(limit=min(max(limit, 1), 200), job_name=job_name)


@app.get("/api/admin/jobs/runs/{run_id}", response_model=JobRunDetail)
def admin_job_run_detail(run_id: str) -> JobRunDetail:
    detail = tracking_job_run_detail(run_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Unknown tracking job run.")
    return detail


@app.post("/api/admin/jobs/runs/{run_id}/steps/{step_name}/rerun", response_model=JobRunDetail)
def admin_job_step_rerun(run_id: str, step_name: str) -> JobRunDetail:
    try:
        detail = rerun_tracking_job_step(run_id, step_name)
    except KeyError:
        raise HTTPException(status_code=404, detail="Unknown tracking job run or step.") from None
    except ValueError:
        raise HTTPException(status_code=409, detail="Step is not eligible for rerun.") from None
    return detail


@app.get("/api/admin/notifications", response_model=list[AppNotification])
def admin_notifications(unread_only: bool = False, limit: int = 50) -> list[AppNotification]:
    return list_app_notifications(unread_only=unread_only, limit=min(max(limit, 1), 200))


@app.post("/api/admin/notifications/{notification_id}/read", response_model=AppNotification)
def admin_notification_read(notification_id: str) -> AppNotification:
    notification = mark_app_notification_read(notification_id)
    if notification is None:
        raise HTTPException(status_code=404, detail="Unknown notification.")
    return notification


@app.get("/api/agents/runs", response_model=list[AgentRun])
def agent_runs(limit: int = 30) -> list[AgentRun]:
    return list_agent_runs(limit=min(max(limit, 1), 100))


@app.get("/api/agents/runs/{run_id}", response_model=AgentRunDetail)
def agent_run_detail(run_id: str) -> AgentRunDetail:
    detail = get_agent_run_detail(run_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Unknown Agent run.")
    return detail


@app.get("/api/agents/actions", response_model=list[AgentAction])
def agent_actions(status: str | None = None, limit: int = 100) -> list[AgentAction]:
    return list_agent_actions(status=status, limit=min(max(limit, 1), 300))


@app.post("/api/agents/actions/{action_id}/approve", response_model=AgentAction)
def approve_agent_action(action_id: str) -> AgentAction:
    updated = apply_agent_action(action_id)
    if updated is None:
        raise HTTPException(status_code=404, detail="Pending Agent action not found.")
    return updated


@app.post("/api/agents/actions/{action_id}/reject", response_model=AgentAction)
def reject_agent_action(action_id: str) -> AgentAction:
    updated = set_agent_action_status(action_id, "rejected")
    if updated is None:
        raise HTTPException(status_code=404, detail="Pending Agent action not found.")
    return updated


@app.get("/api/agents/usage", response_model=AgentUsageSummary)
def agent_usage() -> AgentUsageSummary:
    return agent_usage_summary()


@app.post("/api/assistant/query", response_model=AssistantAnswer)
def assistant_query(payload: AssistantQuery) -> AssistantAnswer:
    compliance = check_text(payload.query)
    if not compliance.allowed:
        answer = AssistantAnswer(
            answer=blocked_answer(payload.query),
            citations=[live_source()],
            evidence=["触发合规边界：" + "、".join(compliance.blocked_terms)],
            confidence=Confidence.high,
            blocked_by_compliance=True,
            missing_information=[],
            disclaimer=DISCLAIMER,
        )
        save_assistant_query(payload.query, answer)
        return answer

    research_answer = run_research_query_agent(payload.query)
    if research_answer is not None:
        save_assistant_query(payload.query, research_answer)
        return research_answer

    temperature, _, sectors, watchlist, events, source = current_market()
    top_sector = sectors[0]
    evidence = [
        f"上涨 {temperature.advancers} 家，下跌 {temperature.decliners} 家",
        f"{top_sector.name}板块涨跌幅 {top_sector.change_pct:+.2f}%",
        f"实时事件数 {len(events)}",
    ]
    if watchlist:
        first = watchlist[0]
        evidence.append(f"自选股 {first.symbol} 最新涨跌幅 {first.change_pct:+.2f}%")
    answer = AssistantAnswer(
        answer=(
            f"基于实时 A 股行情：当前市场温度 {temperature.score}，"
            f"上涨 {temperature.advancers} 家、下跌 {temperature.decliners} 家；"
            f"{top_sector.name}板块当前排序靠前，涨跌幅 {top_sector.change_pct:+.2f}%。"
            "以上只是不含本地假数据的实时信息整理，不构成投资建议。"
        ),
        citations=[source],
        evidence=evidence,
        confidence=Confidence.medium,
        blocked_by_compliance=False,
        missing_information=[],
        disclaimer=DISCLAIMER,
    )
    save_assistant_query(payload.query, answer)
    return answer


@app.post("/api/compliance/check", response_model=ComplianceCheck)
def compliance_check(payload: dict[str, str]) -> ComplianceCheck:
    return check_text(payload.get("text", ""))


@app.get("/api/admin/agents", response_model=AgentStatusResponse)
def agent_status() -> AgentStatusResponse:
    postgres_ok = check_postgres()
    redis_ok = check_redis()
    latest_runs = list_agent_runs(limit=1, workflow="post_market") if postgres_ok else []
    agents = build_agent_statuses(
        postgres_ok,
        redis_ok,
        latest_run=latest_runs[0] if latest_runs else None,
        llm_configured=OpenAICompatibleClient().configured,
    )
    failures = sum(agent.failure_count_24h for agent in agents)
    return AgentStatusResponse(
        agents=agents,
        failure_count_24h=failures,
        data_sources=[*market_provider_sources(), *history_provider_sources(), *information_provider_sources()],
        data_source_statuses=data_source_statuses(),
    )


@app.get("/api/admin/assistant-queries")
def assistant_query_history(limit: int = 50) -> dict[str, object]:
    return {"items": list_assistant_queries(limit=limit)}


@app.post("/api/admin/jobs/{job_name}/rerun")
def rerun_job(job_name: str) -> dict[str, str]:
    postgres_ok = check_postgres()
    redis_ok = check_redis()
    latest_runs = list_agent_runs(limit=1, workflow="post_market") if postgres_ok else []
    agents = build_agent_statuses(
        postgres_ok,
        redis_ok,
        latest_run=latest_runs[0] if latest_runs else None,
        llm_configured=OpenAICompatibleClient().configured,
    )
    known = {agent.name.lower().replace(" ", "-"): agent.name for agent in agents}
    if job_name not in known:
        raise HTTPException(status_code=404, detail="Unknown agent job.")
    return {"status": "queued", "job": known[job_name], "message": "任务已接收；接入 Celery/Temporal 后会由独立 Worker 执行。"}
