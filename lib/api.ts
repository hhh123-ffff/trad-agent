import type {
  AgentStatusResponse,
  AssistantAnswer,
  DashboardResponse,
  DailyTrackingReport,
  InformationSummary,
  JobRun,
  MarketEvent,
  MarketSnapshot,
  NewsItem,
  AnnouncementItem,
  PreopenBrief,
  ReplayReport,
  StealthCandidate,
  StealthCandidateDetail,
  StealthScanFailure,
  StealthScanMonitor,
  StealthScanTask,
  ObservationItem,
  ObservationJournalEntry,
  ObservationSummary,
  WatchlistItemCreate,
  WatchlistResponse,
  WatchlistStock
} from "@/lib/types";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8000";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    cache: "no-store",
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {})
    }
  });

  if (!response.ok) {
    let detail = "";
    try {
      const payload = (await response.json()) as { detail?: unknown };
      detail = typeof payload.detail === "string" ? `：${payload.detail}` : "";
      detail = typeof payload.detail === "string" ? `: ${payload.detail}` : detail;
    } catch {
      detail = "";
    }
    throw new Error(`API ${path} failed with ${response.status}${detail}`);
  }

  return response.json() as Promise<T>;
}

export async function loadDashboard() {
  return request<DashboardResponse>("/api/dashboard");
}

export async function loadPreopen() {
  return request<PreopenBrief>("/api/preopen");
}

export async function loadReplay() {
  return request<ReplayReport>("/api/replay");
}

export async function loadAgents() {
  return request<AgentStatusResponse>("/api/admin/agents");
}

export async function askAssistant(query: string) {
  return request<AssistantAnswer>("/api/assistant/query", {
    method: "POST",
    body: JSON.stringify({ query, user_tier: "pro" })
  });
}

export async function createWatchlistItem(payload: WatchlistItemCreate) {
  return request<WatchlistStock>("/api/watchlist", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export async function deleteWatchlistItem(symbol: string) {
  return request<{ deleted: boolean; symbol: string }>(`/api/watchlist/${encodeURIComponent(symbol)}`, {
    method: "DELETE"
  });
}

export async function loadWatchlist() {
  return request<WatchlistResponse>("/api/watchlist");
}

export async function loadStealthCandidates(params?: { stage?: string; minScore?: number; limit?: number }) {
  const query = new URLSearchParams();
  if (params?.stage) {
    query.set("stage", params.stage);
  }
  if (typeof params?.minScore === "number") {
    query.set("min_score", params.minScore.toString());
  }
  if (typeof params?.limit === "number") {
    query.set("limit", params.limit.toString());
  }
  const suffix = query.toString() ? `?${query.toString()}` : "";
  return request<StealthCandidate[]>(`/api/stealth/candidates${suffix}`);
}

export async function loadStealthDiagnostics(params?: { minScore?: number; limit?: number }) {
  const query = new URLSearchParams();
  if (typeof params?.minScore === "number") {
    query.set("min_score", params.minScore.toString());
  }
  if (typeof params?.limit === "number") {
    query.set("limit", params.limit.toString());
  }
  const suffix = query.toString() ? `?${query.toString()}` : "";
  return request<StealthCandidate[]>(`/api/stealth/diagnostics${suffix}`);
}

export async function loadStealthCandidate(symbol: string) {
  return request<StealthCandidateDetail>(`/api/stealth/candidates/${encodeURIComponent(symbol)}`);
}

export async function runStealthScan(options?: number | { limit?: number; offset?: number; symbols?: string[] }) {
  const body = typeof options === "number" ? { limit: options } : options ?? {};
  return request<StealthScanTask>("/api/stealth/scan/run", {
    method: "POST",
    body: JSON.stringify(body)
  });
}

export async function loadStealthScanTask(taskId: string) {
  return request<StealthScanTask>(`/api/stealth/scan/tasks/${encodeURIComponent(taskId)}`);
}

export async function loadLatestStealthScanTask() {
  return request<StealthScanTask | null>("/api/stealth/scan/tasks/latest");
}

export async function loadStealthScanMonitor() {
  return request<StealthScanMonitor>("/api/stealth/scan/monitor");
}

export async function loadStealthObservations() {
  return request<ObservationItem[]>("/api/stealth/observations");
}

export async function loadStealthObservationSummary() {
  return request<ObservationSummary>("/api/stealth/observations/summary");
}

export async function loadStealthObservationJournal(params?: { symbol?: string; limit?: number }) {
  const query = new URLSearchParams();
  if (params?.symbol) {
    query.set("symbol", params.symbol);
  }
  if (typeof params?.limit === "number") {
    query.set("limit", params.limit.toString());
  }
  const suffix = query.toString() ? `?${query.toString()}` : "";
  return request<ObservationJournalEntry[]>(`/api/stealth/observations/journal${suffix}`);
}

export async function snapshotStealthObservationJournal() {
  return request<ObservationJournalEntry[]>("/api/stealth/observations/journal/snapshot", {
    method: "POST"
  });
}

export async function runStealthObservationScan() {
  return request<StealthScanTask>("/api/stealth/observations/scan", {
    method: "POST"
  });
}

export async function loadStealthScanFailures(taskId: string, unresolvedOnly = false) {
  const query = unresolvedOnly ? "?unresolved_only=true" : "";
  return request<StealthScanFailure[]>(`/api/stealth/scan/tasks/${encodeURIComponent(taskId)}/failures${query}`);
}

export async function retryStealthScanFailures(taskId: string) {
  return request<StealthScanTask>(`/api/stealth/scan/tasks/${encodeURIComponent(taskId)}/retry-failures`, {
    method: "POST"
  });
}

export async function resolveStealthScanFailures(taskId: string) {
  return request<{ task_id: string; resolved: number }>(`/api/stealth/scan/tasks/${encodeURIComponent(taskId)}/resolve-failures`, {
    method: "POST"
  });
}

export type ObservationPayload = {
  reason?: string;
  note?: string;
  invalidation_rule?: string;
  next_focus?: string;
};

export async function observeStealthCandidate(symbol: string, reasonOrPayload: string | ObservationPayload = "") {
  const payload = typeof reasonOrPayload === "string" ? { reason: reasonOrPayload } : reasonOrPayload;
  return request<ObservationItem>(`/api/stealth/observe/${encodeURIComponent(symbol)}`, {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export async function updateStealthObservation(symbol: string, payload: ObservationPayload) {
  return request<ObservationItem>(`/api/stealth/observe/${encodeURIComponent(symbol)}`, {
    method: "PATCH",
    body: JSON.stringify(payload)
  });
}

export async function deleteStealthObservation(symbol: string) {
  return request<{ deleted: boolean; symbol: string }>(`/api/stealth/observe/${encodeURIComponent(symbol)}`, {
    method: "DELETE"
  });
}

export async function loadTrackingDaily(date?: string) {
  const query = new URLSearchParams();
  if (date) query.set("date", date);
  const suffix = query.toString() ? `?${query.toString()}` : "";
  return request<DailyTrackingReport>(`/api/tracking/daily${suffix}`);
}

export async function loadTrackingEvents(params?: { date?: string; symbol?: string; type?: string }) {
  const query = new URLSearchParams();
  if (params?.date) query.set("date", params.date);
  if (params?.symbol) query.set("symbol", params.symbol);
  if (params?.type) query.set("type", params.type);
  const suffix = query.toString() ? `?${query.toString()}` : "";
  return request<MarketEvent[]>(`/api/tracking/events${suffix}`);
}

export async function loadTrackingSnapshots(params?: { date?: string; interval?: string }) {
  const query = new URLSearchParams();
  if (params?.date) query.set("date", params.date);
  if (params?.interval) query.set("interval", params.interval);
  const suffix = query.toString() ? `?${query.toString()}` : "";
  return request<MarketSnapshot[]>(`/api/tracking/snapshots${suffix}`);
}

export async function loadInformationSummary(params?: { date?: string; symbol?: string }) {
  const query = new URLSearchParams();
  if (params?.date) query.set("date", params.date);
  if (params?.symbol) query.set("symbol", params.symbol);
  const suffix = query.toString() ? `?${query.toString()}` : "";
  return request<InformationSummary>(`/api/tracking/information-summary${suffix}`);
}

export async function runAdminJob(jobName: string) {
  return request<JobRun>(`/api/admin/jobs/run/${encodeURIComponent(jobName)}`, {
    method: "POST"
  });
}

export async function loadAdminJobRuns(params?: { limit?: number; jobName?: string }) {
  const query = new URLSearchParams();
  if (typeof params?.limit === "number") query.set("limit", params.limit.toString());
  if (params?.jobName) query.set("job_name", params.jobName);
  const suffix = query.toString() ? `?${query.toString()}` : "";
  return request<JobRun[]>(`/api/admin/jobs/runs${suffix}`);
}

export async function loadNewsItems(params?: { date?: string; symbol?: string }) {
  const query = new URLSearchParams();
  if (params?.date) query.set("date", params.date);
  if (params?.symbol) query.set("symbol", params.symbol);
  const suffix = query.toString() ? `?${query.toString()}` : "";
  return request<NewsItem[]>(`/api/news${suffix}`);
}

export async function loadAnnouncementItems(params?: { date?: string; symbol?: string }) {
  const query = new URLSearchParams();
  if (params?.date) query.set("date", params.date);
  if (params?.symbol) query.set("symbol", params.symbol);
  const suffix = query.toString() ? `?${query.toString()}` : "";
  return request<AnnouncementItem[]>(`/api/announcements${suffix}`);
}
