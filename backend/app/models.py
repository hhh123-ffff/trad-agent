from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class PlanTier(str, Enum):
    free = "free"
    pro = "pro"
    premium = "premium"


class EventType(str, Enum):
    announcement = "announcement"
    earnings = "earnings"
    policy = "policy"
    limit_up = "limit_up"
    limit_down = "limit_down"
    volume_spike = "volume_spike"
    sector_rotation = "sector_rotation"
    capital_flow = "capital_flow"
    watchlist = "watchlist"
    risk = "risk"


class Confidence(str, Enum):
    high = "high"
    medium = "medium"
    low = "low"


class SourceRef(BaseModel):
    id: str
    name: str
    url: str
    as_of: datetime
    license: str = "unspecified"
    freshness: str


class MarketIndex(BaseModel):
    symbol: str
    name: str
    value: float
    change_pct: float
    turnover_billion: float
    source_id: str


class SectorSnapshot(BaseModel):
    name: str
    change_pct: float
    turnover_billion: float
    leading_symbols: list[str]
    driver: str
    confidence: Confidence
    source_id: str


class WatchlistStock(BaseModel):
    symbol: str
    name: str
    group: str
    price: float
    change_pct: float
    volume_ratio: float
    tags: list[str]
    attention_reason: str
    latest_event: str
    risk_flags: list[str]
    source_id: str


class WatchlistItemCreate(BaseModel):
    symbol: str = Field(min_length=2, max_length=16)
    name: str = Field(default="自动识别", min_length=1, max_length=64)
    group: str = Field(default="默认分组", max_length=32)
    price: float = 0
    change_pct: float = 0
    volume_ratio: float = 1
    tags: list[str] = Field(default_factory=list)
    attention_reason: str = "手动加入自选股，等待下一轮数据扫描。"
    latest_event: str = "暂无事件，等待盘中 Radar 扫描。"
    risk_flags: list[str] = Field(default_factory=list)
    source_id: str = "src-eastmoney-live"


class WatchlistItemUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    group: str | None = Field(default=None, max_length=32)
    price: float | None = None
    change_pct: float | None = None
    volume_ratio: float | None = None
    tags: list[str] | None = None
    attention_reason: str | None = None
    latest_event: str | None = None
    risk_flags: list[str] | None = None
    source_id: str | None = None


class MarketTemperature(BaseModel):
    score: int = Field(ge=0, le=100)
    label: str
    advancers: int
    decliners: int
    limit_up_count: int
    limit_down_count: int
    total_turnover_billion: float
    updated_at: datetime


class MarketEvent(BaseModel):
    id: str
    occurred_at: datetime
    type: EventType
    title: str
    summary: str
    affected_symbols: list[str]
    affected_sectors: list[str]
    importance: Literal["critical", "high", "medium", "low"]
    fact_basis: list[str]
    inference: str | None = None
    confidence: Confidence
    source_ids: list[str]
    compliance_label: Literal["fact", "inference", "risk"]


class BriefItem(BaseModel):
    title: str
    detail: str
    importance: Literal["critical", "high", "medium", "low"]
    impact_scope: list[str]
    source_ids: list[str]
    action_boundary: str = "仅供信息整理，不构成投资建议。"


class PreopenBrief(BaseModel):
    generated_at: datetime
    version: str
    readiness: int = Field(ge=0, le=100)
    must_watch: list[BriefItem]
    watchlist_impacts: list[BriefItem]
    sector_clues: list[BriefItem]
    risk_events: list[BriefItem]
    calendar: list[BriefItem]
    sources: list[SourceRef]


class ReplaySection(BaseModel):
    window: str
    title: str
    summary: str
    missed_signals: list[MarketEvent]
    source_ids: list[str]


class ReplayReport(BaseModel):
    trading_day: str
    generated_at: datetime
    headline: str
    market_summary: str
    sections: list[ReplaySection]
    watchlist_summary: list[BriefItem]
    sources: list[SourceRef]


class DashboardResponse(BaseModel):
    temperature: MarketTemperature
    indexes: list[MarketIndex]
    sectors: list[SectorSnapshot]
    watchlist: list[WatchlistStock]
    events: list[MarketEvent]
    sources: list[SourceRef]
    disclaimer: str


class StockProfile(BaseModel):
    symbol: str
    name: str
    sector: str
    price: float
    change_pct: float
    returns: dict[str, float]
    fundamentals: dict[str, str | float]
    themes: list[str]
    risk_flags: list[str]
    recent_events: list[MarketEvent]
    sources: list[SourceRef]
    disclaimer: str


class AgentStatus(BaseModel):
    name: str
    purpose: str
    status: Literal["healthy", "degraded", "paused"]
    last_run_at: datetime
    next_run_at: datetime | None
    latest_message: str
    failure_count_24h: int


class DataSourceStatus(BaseModel):
    id: str
    name: str
    provider: str
    status: Literal["configured", "missing_credentials", "fallback", "not_enabled"]
    capabilities: dict[str, str] = Field(default_factory=dict)
    latest_error: str | None = None
    last_success_at: datetime | None = None
    next_step: str = ""


class AgentStatusResponse(BaseModel):
    agents: list[AgentStatus] = Field(default_factory=list)
    failure_count_24h: int = 0
    data_sources: list[SourceRef] = Field(default_factory=list)
    data_source_statuses: list[DataSourceStatus] = Field(default_factory=list)


class AssistantQuery(BaseModel):
    query: str = Field(min_length=2, max_length=500)
    user_tier: PlanTier = PlanTier.free
    watchlist_symbols: list[str] = Field(default_factory=list)


class AssistantAnswer(BaseModel):
    answer: str
    citations: list[SourceRef]
    evidence: list[str]
    confidence: Confidence
    blocked_by_compliance: bool
    missing_information: list[str]
    disclaimer: str


class ComplianceCheck(BaseModel):
    text: str
    allowed: bool
    blocked_terms: list[str]
    rewritten_guidance: str


StealthStage = Literal["潜伏观察", "启动确认", "过热排除", "数据不足"]


class StockUniverseItem(BaseModel):
    symbol: str
    name: str
    is_st: bool = False
    listed_days: int = 0
    market: str = "A股"


class DailyBar(BaseModel):
    symbol: str
    trade_date: date
    open: float
    high: float
    low: float
    close: float
    volume: float = 0
    amount: float = 0
    change_pct: float = 0
    turnover_rate: float = 0
    adjust: str = "qfq"


class ThemeMembership(BaseModel):
    symbol: str
    theme_name: str
    theme_type: Literal["industry", "concept", "custom"] = "concept"


class StealthCandidate(BaseModel):
    trading_day: date
    symbol: str
    name: str
    stage: StealthStage
    total_score: float = Field(ge=0, le=100)
    accumulation_score: float = Field(ge=0, le=100)
    launch_score: float = Field(ge=0, le=100)
    theme_score: float = Field(ge=0, le=100)
    risk_penalty: float = Field(ge=0, le=100)
    evidence: list[str]
    risks: list[str]
    metrics: dict[str, Any] = Field(default_factory=dict)
    themes: list[str] = Field(default_factory=list)
    observed: bool = False
    source_ids: list[str] = Field(default_factory=list)
    disclaimer: str = "仅供研究筛选和观察辅助，不构成投资建议。"


class StealthCandidateDetail(BaseModel):
    candidate: StealthCandidate
    bars: list[DailyBar]
    weekly_bars: list[DailyBar]
    source_refs: list[SourceRef]


class StealthScanRunRequest(BaseModel):
    limit: int | None = Field(default=None, ge=1, le=6000)
    offset: int = Field(default=0, ge=0, le=10000)
    symbols: list[str] = Field(default_factory=list)


class StealthScanRunResponse(BaseModel):
    trading_day: date
    total: int = 0
    scanned: int
    saved: int
    failed: int = 0
    stages: dict[str, int]
    message: str


StealthScanTaskStatus = Literal["queued", "running", "completed", "failed"]


class StealthScanTask(BaseModel):
    id: str
    status: StealthScanTaskStatus
    requested_limit: int | None = None
    requested_offset: int = 0
    requested_symbols: list[str] = Field(default_factory=list)
    active_themes: list[str] = Field(default_factory=list)
    total: int = 0
    scanned: int = 0
    saved: int = 0
    failed: int = 0
    stages: dict[str, int] = Field(default_factory=dict)
    message: str = ""
    error: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    updated_at: datetime


class StealthScanAlert(BaseModel):
    level: Literal["info", "warning", "critical"]
    message: str
    metric: str
    value: float | int | str | None = None


class StealthDataQualitySummary(BaseModel):
    latest_trade_date: date | None = None
    universe_symbols: int = 0
    symbols_with_bars: int = 0
    latest_bar_symbols: int = 0
    zero_amount_symbols: int = 0
    short_history_symbols: int = 0
    stale_symbols: int = 0
    checked_at: datetime


class StealthScanMonitor(BaseModel):
    latest_tasks: list[StealthScanTask] = Field(default_factory=list)
    running_task: StealthScanTask | None = None
    avg_duration_seconds: float = 0
    latest_failure_rate: float = 0
    unresolved_failures: int = 0
    data_quality: StealthDataQualitySummary
    alerts: list[StealthScanAlert] = Field(default_factory=list)


class StealthScanFailure(BaseModel):
    id: int
    task_id: str
    symbol: str
    name: str = ""
    stage: str = "history"
    error: str = ""
    retry_count: int = 0
    resolved: bool = False
    created_at: datetime
    updated_at: datetime


class ObservationRequest(BaseModel):
    reason: str = Field(default="", max_length=300)
    note: str = Field(default="", max_length=500)
    invalidation_rule: str = Field(default="", max_length=500)
    next_focus: str = Field(default="", max_length=500)


class ObservationItem(BaseModel):
    symbol: str
    reason: str
    status: str
    note: str
    invalidation_rule: str = ""
    next_focus: str = ""
    candidate: StealthCandidate | None = None
    invalidation_reasons: list[str] = Field(default_factory=list)
    days_observed: int = 0
    created_at: datetime
    updated_at: datetime


class ObservationSummaryBucket(BaseModel):
    key: Literal["continue", "activation", "invalid", "data_gap"]
    label: str
    count: int = 0
    items: list[ObservationItem] = Field(default_factory=list)


class ObservationSummary(BaseModel):
    total: int = 0
    continue_count: int = 0
    activation_count: int = 0
    invalid_count: int = 0
    data_gap_count: int = 0
    updated_at: datetime
    buckets: list[ObservationSummaryBucket] = Field(default_factory=list)


class ObservationJournalEntry(BaseModel):
    symbol: str
    trading_day: date
    name: str = ""
    bucket_key: Literal["continue", "activation", "invalid", "data_gap"]
    bucket_label: str
    previous_bucket_key: str | None = None
    transition_label: str
    stage: str = ""
    total_score: float | None = None
    accumulation_score: float | None = None
    launch_score: float | None = None
    theme_score: float | None = None
    risk_penalty: float | None = None
    decision_summary: str
    observation_reason: str = ""
    manual_invalidation_rule: str = ""
    next_focus: str = ""
    evidence: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    invalidation_reasons: list[str] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class ProviderMeta(BaseModel):
    provider: str
    source_id: str
    fetched_at: datetime
    license_note: str


class JobRun(BaseModel):
    id: str
    job_name: str
    status: Literal["queued", "running", "completed", "failed"]
    started_at: datetime
    finished_at: datetime | None = None
    duration_ms: int = 0
    affected_scope: dict[str, Any] = Field(default_factory=dict)
    message: str = ""
    error: str | None = None
    created_at: datetime
    updated_at: datetime


class MarketSnapshot(BaseModel):
    id: str
    captured_at: datetime
    interval: str = "5m"
    provider: str
    source_id: str
    license_note: str
    market_temperature: MarketTemperature
    indexes: list[MarketIndex] = Field(default_factory=list)
    sectors: list[SectorSnapshot] = Field(default_factory=list)
    watchlist: list[WatchlistStock] = Field(default_factory=list)
    event_ids: list[str] = Field(default_factory=list)


class NewsItem(BaseModel):
    id: str
    symbol: str | None = None
    title: str
    summary: str = ""
    published_at: datetime
    source_url: str = ""
    source_name: str = ""
    event_type: str = "news"
    importance: Literal["critical", "high", "medium", "low"] = "medium"
    provider: str = "dev"
    source_id: str = "src-dev-news"
    license_note: str = "研发源，仅保存标题摘要和链接"


class AnnouncementItem(BaseModel):
    id: str
    symbol: str | None = None
    title: str
    summary: str = ""
    published_at: datetime
    source_url: str = ""
    source_name: str = ""
    event_type: str = "announcement"
    importance: Literal["critical", "high", "medium", "low"] = "medium"
    provider: str = "dev"
    source_id: str = "src-dev-announcement"
    license_note: str = "研发源，仅保存标题摘要和链接"


class InformationDigestItem(BaseModel):
    id: str
    symbol: str | None = None
    title: str
    summary: str = ""
    published_at: datetime
    source_url: str = ""
    source_name: str = ""
    event_type: Literal["news", "announcement"]
    importance: Literal["critical", "high", "medium", "low"] = "medium"
    source_id: str


class InformationSymbolSummary(BaseModel):
    symbol: str
    total: int = 0
    news: int = 0
    announcements: int = 0
    high_importance: int = 0
    latest_title: str = ""
    latest_at: datetime | None = None


class InformationSummary(BaseModel):
    trading_day: date
    total_count: int = 0
    news_count: int = 0
    announcement_count: int = 0
    by_importance: dict[str, int] = Field(default_factory=dict)
    by_event_type: dict[str, int] = Field(default_factory=dict)
    by_symbol: list[InformationSymbolSummary] = Field(default_factory=list)
    latest_items: list[InformationDigestItem] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)


class DailyTrackingReport(BaseModel):
    trading_day: date
    generated_at: datetime
    headline: str
    summary: str
    sections: list[dict[str, Any]] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)
    snapshots: list[MarketSnapshot] = Field(default_factory=list)
    events: list[MarketEvent] = Field(default_factory=list)
    news: list[NewsItem] = Field(default_factory=list)
    announcements: list[AnnouncementItem] = Field(default_factory=list)


class TrackingEventsResponse(BaseModel):
    items: list[MarketEvent]


class TrackingSnapshotsResponse(BaseModel):
    items: list[MarketSnapshot]
