import type { DataFreshnessResult, JobRun, JobRunDetail, JobRunStep, JobRunStepStatus } from "@/lib/types";

export type PipelineStatus = JobRunStepStatus;

export interface JobPipelineStep {
  key: "close_snapshot" | "collect_information" | "stealth_scan" | "observation_journal" | "daily_report" | "agent_post_market";
  label: string;
  status: PipelineStatus;
  detail: string;
  attempts: number;
  durationMs: number;
  errorCode: string | null;
  retryable: boolean;
}

function scopeObject(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
}

function statusValue(value: unknown): PipelineStatus {
  return value === "running" || value === "completed" || value === "degraded" || value === "failed" || value === "skipped" ? value : "pending";
}

function textValue(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function numberValue(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

function numericTimestamp(run: JobRun): number {
  const parsed = Date.parse(run.finished_at ?? run.started_at ?? run.updated_at ?? run.created_at);
  return Number.isFinite(parsed) ? parsed : 0;
}

export function latestPostMarketRun(jobRuns: JobRun[]): JobRun | null {
  return jobRuns
    .filter((run) => run.job_name === "post_market_replay")
    .reduce<JobRun | null>((latest, run) => {
      if (!latest) return run;
      return numericTimestamp(run) > numericTimestamp(latest) ? run : latest;
    }, null);
}

export function postMarketPipeline(run: JobRun | null): JobPipelineStep[] {
  const scope = scopeObject(run?.affected_scope);
  const durableSteps = scopeObject(scope.steps);
  const snapshot = scopeObject(durableSteps.close_snapshot ?? scope.snapshot);
  const information = scopeObject(durableSteps.collect_information ?? scope.information);
  const scan = scopeObject(durableSteps.stealth_scan ?? scope.scan);
  const journal = scopeObject(durableSteps.observation_journal);
  const report = scopeObject(durableSteps.daily_report);
  const agent = scopeObject(durableSteps.agent_post_market);

  const snapshotEvents = numberValue(snapshot.events ?? scope.events);
  const news = numberValue(information.news ?? scope.news);
  const announcements = numberValue(information.announcements ?? scope.announcements);
  const scanned = numberValue(scan.scanned);
  const saved = numberValue(scan.saved);
  const journalCount = numberValue(scope.observation_journal);
  const reportSections = numberValue(scope.report_sections);

  return [
    {
      key: "close_snapshot",
      label: "收盘快照",
      status: inferredScopeStatus(snapshot),
      detail: textValue(snapshot.error) || `Events: ${snapshotEvents}`,
      attempts: 0,
      durationMs: 0,
      errorCode: null,
      retryable: false
    },
    {
      key: "collect_information",
      label: "公告与新闻",
      status: inferredScopeStatus(information),
      detail: textValue(information.error) || `News: ${news} / Announcements: ${announcements}`,
      attempts: 0,
      durationMs: 0,
      errorCode: null,
      retryable: false
    },
    {
      key: "stealth_scan",
      label: "策略扫描",
      status: inferredScopeStatus(scan),
      detail: textValue(scan.error) || textValue(scan.reason) || `Scanned: ${scanned} / Saved: ${saved}`,
      attempts: 0,
      durationMs: 0,
      errorCode: null,
      retryable: false
    },
    {
      key: "observation_journal",
      label: "观察池日志",
      status: inferredScopeStatus(journal, typeof scope.observation_journal === "number"),
      detail: `Records: ${numberValue(journal.observation_journal) || journalCount}`,
      attempts: 0,
      durationMs: 0,
      errorCode: null,
      retryable: false
    },
    {
      key: "daily_report",
      label: "确定性日报",
      status: inferredScopeStatus(report, typeof scope.report_sections === "number"),
      detail: `Sections: ${numberValue(report.sections) || reportSections}`,
      attempts: 0,
      durationMs: 0,
      errorCode: null,
      retryable: false
    },
    {
      key: "agent_post_market",
      label: "Agent 简报",
      status: Object.keys(agent).length > 0 ? statusValue(agent.status ?? agent.agent_status) : "pending",
      detail: textValue(agent.reason) || textValue(agent.agent_status) || "等待确定性日报",
      attempts: 0,
      durationMs: 0,
      errorCode: null,
      retryable: false
    },
  ];
}

const STEP_LABELS: Record<JobPipelineStep["key"], string> = {
  close_snapshot: "收盘快照",
  collect_information: "公告与新闻",
  stealth_scan: "策略扫描",
  observation_journal: "观察池日志",
  daily_report: "确定性日报",
  agent_post_market: "Agent 简报"
};

export function detailedPostMarketPipeline(detail: JobRunDetail | null): JobPipelineStep[] {
  const grouped = new Map<string, JobRunStep[]>();
  for (const step of detail?.steps ?? []) {
    grouped.set(step.step_name, [...(grouped.get(step.step_name) ?? []), step]);
  }
  return (Object.keys(STEP_LABELS) as JobPipelineStep["key"][]).map((key) => {
    const attempts = grouped.get(key) ?? [];
    const latest = attempts.at(-1);
    return {
      key,
      label: STEP_LABELS[key],
      status: latest?.status ?? "pending",
      detail: latest ? stepDetail(latest) : "尚未执行",
      attempts: attempts.length,
      durationMs: latest?.duration_ms ?? 0,
      errorCode: latest?.error_code ?? null,
      retryable: Boolean(latest && (latest.retryable || latest.status === "degraded" || latest.status === "skipped"))
    };
  });
}

export function jobRunFreshness(run: JobRun | null): DataFreshnessResult | null {
  const scope = scopeObject(run?.affected_scope);
  const freshness = scopeObject(scope.data_freshness);
  if (!freshness.status || !Array.isArray(freshness.checks)) return null;
  return freshness as unknown as DataFreshnessResult;
}

function stepDetail(step: JobRunStep): string {
  if (step.error) return step.error;
  const entries = Object.entries(step.result_scope)
    .filter(([, value]) => typeof value === "string" || typeof value === "number")
    .slice(0, 3)
    .map(([key, value]) => `${key}: ${value}`);
  return entries.join(" · ") || "步骤已记录";
}

function inferredScopeStatus(scope: Record<string, unknown>, legacyCompleted = false): PipelineStatus {
  const explicit = statusValue(scope.status);
  if (explicit !== "pending") return explicit;
  if (typeof scope.action === "string") return "failed";
  if (typeof scope.reason === "string") return "skipped";
  if (legacyCompleted || Object.keys(scope).length > 0) return "completed";
  return "pending";
}
