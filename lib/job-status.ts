import type { JobRun } from "@/lib/types";

export type PipelineStatus = "completed" | "failed" | "skipped" | "pending";

export interface JobPipelineStep {
  key: "snapshot" | "information" | "scan" | "observation_journal" | "report";
  label: string;
  status: PipelineStatus;
  detail: string;
}

function scopeObject(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
}

function statusValue(value: unknown): PipelineStatus {
  return value === "completed" || value === "failed" || value === "skipped" ? value : "pending";
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
  const snapshot = scopeObject(scope.snapshot);
  const information = scopeObject(scope.information);
  const scan = scopeObject(scope.scan);

  const snapshotEvents = numberValue(snapshot.events ?? scope.events);
  const news = numberValue(information.news ?? scope.news);
  const announcements = numberValue(information.announcements ?? scope.announcements);
  const scanned = numberValue(scan.scanned);
  const saved = numberValue(scan.saved);
  const journalCount = numberValue(scope.observation_journal);
  const reportSections = numberValue(scope.report_sections);

  return [
    {
      key: "snapshot",
      label: "Market snapshot",
      status: statusValue(snapshot.status),
      detail: textValue(snapshot.error) || `Events: ${snapshotEvents}`,
    },
    {
      key: "information",
      label: "News and announcements",
      status: statusValue(information.status),
      detail: textValue(information.error) || `News: ${news} / Announcements: ${announcements}`,
    },
    {
      key: "scan",
      label: "Stealth scan",
      status: statusValue(scan.status),
      detail: textValue(scan.error) || textValue(scan.reason) || `Scanned: ${scanned} / Saved: ${saved}`,
    },
    {
      key: "observation_journal",
      label: "Observation journal",
      status: typeof scope.observation_journal === "number" ? "completed" : "pending",
      detail: `Records: ${journalCount}`,
    },
    {
      key: "report",
      label: "Daily report",
      status: typeof scope.report_sections === "number" ? "completed" : "pending",
      detail: `Sections: ${reportSections}`,
    },
  ];
}
