export type Confidence = "high" | "medium" | "low";
export type Importance = "critical" | "high" | "medium" | "low";

export interface SourceRef {
  id: string;
  name: string;
  url: string;
  as_of: string;
  license: string;
  freshness: string;
}

export interface DataSourceStatus {
  id: string;
  name: string;
  provider: string;
  status: "configured" | "missing_credentials" | "fallback" | "not_enabled";
  capabilities: Record<string, string>;
  latest_error: string | null;
  last_success_at: string | null;
  next_step: string;
}

export interface MarketTemperature {
  score: number;
  label: string;
  advancers: number;
  decliners: number;
  limit_up_count: number;
  limit_down_count: number;
  total_turnover_billion: number;
  updated_at: string;
}

export interface MarketIndex {
  symbol: string;
  name: string;
  value: number;
  change_pct: number;
  turnover_billion: number;
  source_id: string;
}

export interface SectorSnapshot {
  name: string;
  change_pct: number;
  turnover_billion: number;
  leading_symbols: string[];
  driver: string;
  confidence: Confidence;
  source_id: string;
}

export interface WatchlistStock {
  symbol: string;
  name: string;
  group: string;
  price: number;
  change_pct: number;
  volume_ratio: number;
  tags: string[];
  attention_reason: string;
  latest_event: string;
  risk_flags: string[];
  source_id: string;
}

export interface WatchlistItemCreate {
  symbol: string;
  name?: string;
  group: string;
  tags: string[];
  attention_reason?: string;
}

export interface WatchlistResponse {
  items: WatchlistStock[];
  limit: number;
  tier: string;
  cached_count: number | null;
  disclaimer: string;
}

export interface MarketEvent {
  id: string;
  occurred_at: string;
  type: string;
  title: string;
  summary: string;
  affected_symbols: string[];
  affected_sectors: string[];
  importance: Importance;
  fact_basis: string[];
  inference: string | null;
  confidence: Confidence;
  source_ids: string[];
  compliance_label: "fact" | "inference" | "risk";
}

export interface BriefItem {
  title: string;
  detail: string;
  importance: Importance;
  impact_scope: string[];
  source_ids: string[];
  action_boundary: string;
}

export interface DashboardResponse {
  temperature: MarketTemperature;
  indexes: MarketIndex[];
  sectors: SectorSnapshot[];
  watchlist: WatchlistStock[];
  events: MarketEvent[];
  sources: SourceRef[];
  disclaimer: string;
}

export interface PreopenBrief {
  generated_at: string;
  version: string;
  readiness: number;
  must_watch: BriefItem[];
  watchlist_impacts: BriefItem[];
  sector_clues: BriefItem[];
  risk_events: BriefItem[];
  calendar: BriefItem[];
  sources: SourceRef[];
}

export interface ReplaySection {
  window: string;
  title: string;
  summary: string;
  missed_signals: MarketEvent[];
  source_ids: string[];
}

export interface ReplayReport {
  trading_day: string;
  generated_at: string;
  headline: string;
  market_summary: string;
  sections: ReplaySection[];
  watchlist_summary: BriefItem[];
  sources: SourceRef[];
}

export interface AgentStatus {
  name: string;
  purpose: string;
  status: "healthy" | "degraded" | "paused";
  last_run_at: string;
  next_run_at: string | null;
  latest_message: string;
  failure_count_24h: number;
}

export interface AgentStatusResponse {
  agents: AgentStatus[];
  failure_count_24h: number;
  data_sources: SourceRef[];
  data_source_statuses?: DataSourceStatus[];
}

export interface AssistantAnswer {
  answer: string;
  citations: SourceRef[];
  evidence: string[];
  confidence: Confidence;
  blocked_by_compliance: boolean;
  missing_information: string[];
  disclaimer: string;
}

export type StealthStage = "潜伏观察" | "启动确认" | "过热排除" | "数据不足";

export interface DailyBar {
  symbol: string;
  trade_date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  amount: number;
  change_pct: number;
  turnover_rate: number;
  adjust: string;
}

export interface StealthCandidate {
  trading_day: string;
  symbol: string;
  name: string;
  stage: StealthStage;
  total_score: number;
  accumulation_score: number;
  launch_score: number;
  theme_score: number;
  risk_penalty: number;
  evidence: string[];
  risks: string[];
  metrics: Record<string, string | number>;
  themes: string[];
  observed: boolean;
  source_ids: string[];
  disclaimer: string;
}

export interface StealthCandidateDetail {
  candidate: StealthCandidate;
  bars: DailyBar[];
  weekly_bars: DailyBar[];
  source_refs: SourceRef[];
}

export interface StealthScanRunResponse {
  trading_day: string;
  total: number;
  scanned: number;
  saved: number;
  failed: number;
  stages: Record<string, number>;
  message: string;
}

export type StealthScanTaskStatus = "queued" | "running" | "completed" | "failed";

export interface StealthScanTask {
  id: string;
  status: StealthScanTaskStatus;
  requested_limit: number | null;
  requested_offset: number;
  requested_symbols: string[];
  active_themes: string[];
  total: number;
  scanned: number;
  saved: number;
  failed: number;
  stages: Record<string, number>;
  message: string;
  error: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  updated_at: string;
}

export interface StealthScanAlert {
  level: "info" | "warning" | "critical";
  message: string;
  metric: string;
  value: number | string | null;
}

export interface StealthDataQualitySummary {
  latest_trade_date: string | null;
  universe_symbols: number;
  symbols_with_bars: number;
  latest_bar_symbols: number;
  zero_amount_symbols: number;
  short_history_symbols: number;
  stale_symbols: number;
  checked_at: string;
}

export interface StealthScanMonitor {
  latest_tasks: StealthScanTask[];
  running_task: StealthScanTask | null;
  avg_duration_seconds: number;
  latest_failure_rate: number;
  unresolved_failures: number;
  data_quality: StealthDataQualitySummary;
  alerts: StealthScanAlert[];
}

export interface StealthScanFailure {
  id: number;
  task_id: string;
  symbol: string;
  name: string;
  stage: string;
  error: string;
  retry_count: number;
  resolved: boolean;
  created_at: string;
  updated_at: string;
}

export interface ObservationItem {
  symbol: string;
  reason: string;
  status: string;
  note: string;
  invalidation_rule: string;
  next_focus: string;
  candidate: StealthCandidate | null;
  invalidation_reasons: string[];
  days_observed: number;
  created_at: string;
  updated_at: string;
}

export interface ObservationSummaryBucket {
  key: "continue" | "activation" | "invalid" | "data_gap";
  label: string;
  count: number;
  items: ObservationItem[];
}

export interface ObservationSummary {
  total: number;
  continue_count: number;
  activation_count: number;
  invalid_count: number;
  data_gap_count: number;
  updated_at: string;
  buckets: ObservationSummaryBucket[];
}

export interface ObservationJournalEntry {
  symbol: string;
  trading_day: string;
  name: string;
  bucket_key: "continue" | "activation" | "invalid" | "data_gap";
  bucket_label: string;
  previous_bucket_key: string | null;
  transition_label: string;
  stage: string;
  total_score: number | null;
  accumulation_score: number | null;
  launch_score: number | null;
  theme_score: number | null;
  risk_penalty: number | null;
  decision_summary: string;
  observation_reason: string;
  manual_invalidation_rule: string;
  next_focus: string;
  evidence: string[];
  risks: string[];
  invalidation_reasons: string[];
  source_ids: string[];
  created_at: string;
  updated_at: string;
}

export type JobRunStatus = "queued" | "running" | "completed" | "failed";

export interface JobRun {
  id: string;
  job_name: string;
  status: JobRunStatus;
  started_at: string;
  finished_at: string | null;
  duration_ms: number;
  affected_scope: Record<string, unknown>;
  message: string;
  error: string | null;
  created_at: string;
  updated_at: string;
}

export interface MarketSnapshot {
  id: string;
  captured_at: string;
  interval: string;
  provider: string;
  source_id: string;
  license_note: string;
  market_temperature: MarketTemperature;
  indexes: MarketIndex[];
  sectors: SectorSnapshot[];
  watchlist: WatchlistStock[];
  event_ids: string[];
}

export interface NewsItem {
  id: string;
  symbol: string | null;
  title: string;
  summary: string;
  published_at: string;
  source_url: string;
  source_name: string;
  source_id: string;
  event_type: string;
  importance: Importance;
  provider: string;
  license_note: string;
}

export interface AnnouncementItem {
  id: string;
  symbol: string | null;
  title: string;
  summary: string;
  published_at: string;
  source_url: string;
  source_name: string;
  source_id: string;
  event_type: string;
  importance: Importance;
  provider: string;
  license_note: string;
}

export interface DailyTrackingReport {
  trading_day: string;
  generated_at: string;
  headline: string;
  summary: string;
  sections: Array<{
    title: string;
    summary: string;
    evidence: string[];
    metrics?: Record<string, string | number>;
    warnings?: string[];
  }>;
  source_ids: string[];
  snapshots: MarketSnapshot[];
  events: MarketEvent[];
  news: NewsItem[];
  announcements: AnnouncementItem[];
}
