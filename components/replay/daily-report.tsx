import { AlertTriangle, CheckCircle2, Clock3 } from "lucide-react";

import type { DailyTrackingReport, JobRun } from "@/lib/types";

export function DailyReportCard({
  trackingDaily,
  trackingError,
  jobRuns
}: {
  trackingDaily?: DailyTrackingReport;
  trackingError?: string;
  jobRuns: JobRun[];
}) {
  const trackingJobs = jobRuns
    .filter((run) => ["intraday_snapshot", "close_snapshot", "news_explain", "post_market_replay", "daily_report"].includes(run.job_name))
    .slice(0, 4);

  if (!trackingDaily) {
    return <DailyReportUnavailable error={trackingError} jobRuns={trackingJobs} />;
  }

  return (
    <section className="panel rounded-lg p-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-xs font-semibold text-pine">每日市场分析报告</p>
          <h3 className="mt-1 text-xl font-semibold leading-8">{trackingDaily.headline}</h3>
          <p className="mt-1 text-sm leading-6 text-muted">{trackingDaily.summary}</p>
        </div>
        <div className="flex flex-wrap gap-2 text-xs">
          <span className="rounded-md border border-ink/10 bg-white px-2 py-1">快照 {trackingDaily.snapshots.length}</span>
          <span className="rounded-md border border-ink/10 bg-white px-2 py-1">事件 {trackingDaily.events.length}</span>
          <span className="rounded-md border border-ink/10 bg-white px-2 py-1">新闻 {trackingDaily.news.length}</span>
          <span className="rounded-md border border-ink/10 bg-white px-2 py-1">公告 {trackingDaily.announcements.length}</span>
        </div>
      </div>
      <TrackingJobStrip jobRuns={trackingJobs} />
      <div className="mt-4 grid gap-3 xl:grid-cols-2">
        {trackingDaily.sections.map((section) => (
          <DailyReportSection key={section.title} section={section} />
        ))}
      </div>
    </section>
  );
}

function DailyReportSection({ section }: { section: DailyTrackingReport["sections"][number] }) {
  const metrics = Object.entries(section.metrics ?? {});
  return (
    <article className="rounded-lg border border-ink/10 bg-white p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="text-base font-semibold">{section.title}</h3>
          <p className="mt-2 text-sm leading-6 text-muted">{section.summary}</p>
        </div>
        {section.warnings && section.warnings.length > 0 && (
          <span className="inline-flex items-center gap-1 rounded-md border border-saffron/35 bg-saffron/10 px-2 py-1 text-xs font-semibold text-[#8a5a12]">
            <AlertTriangle size={13} />
            {section.warnings.length} 项缺口
          </span>
        )}
      </div>
      {metrics.length > 0 && (
        <div className="mt-3 grid grid-cols-2 gap-2 md:grid-cols-3">
          {metrics.slice(0, 6).map(([key, value]) => (
            <div key={key} className="rounded-md border border-ink/10 bg-paper px-3 py-2">
              <p className="text-[11px] uppercase text-muted">{key.replaceAll("_", " ")}</p>
              <p className="mt-1 truncate text-sm font-semibold text-ink" title={String(value)}>
                {formatMetricValue(value)}
              </p>
            </div>
          ))}
        </div>
      )}
      {section.warnings && section.warnings.length > 0 && (
        <div className="mt-3 space-y-1">
          {section.warnings.map((warning) => (
            <p key={warning} className="flex break-words gap-2 text-xs leading-5 text-[#8a5a12]">
              <AlertTriangle className="mt-0.5 shrink-0" size={13} />
              {warning}
            </p>
          ))}
        </div>
      )}
      <div className="mt-3 space-y-1">
        {section.evidence.slice(0, 6).map((item) => (
          <p key={item} className="flex break-words gap-2 text-xs leading-5 text-muted">
            <CheckCircle2 className="mt-0.5 shrink-0 text-pine" size={13} />
            {item}
          </p>
        ))}
      </div>
    </article>
  );
}

function DailyReportUnavailable({ error, jobRuns }: { error?: string; jobRuns: JobRun[] }) {
  return (
    <section className="panel rounded-lg p-5">
      <div className="rounded-lg border border-saffron/30 bg-saffron/10 p-4">
        <div className="flex items-center gap-2 text-[#8a5a12]">
          <AlertTriangle size={17} />
          <h3 className="text-sm font-semibold">每日报告尚未加载</h3>
        </div>
        <p className="mt-2 text-sm leading-6 text-muted">
          可以在“数据状态”里依次运行盘中快照、收盘快照和每日报告；如果数据库或行情源暂不可用，这里会在恢复后重新显示。
        </p>
        {error && <p className="mt-3 break-words rounded-md border border-danger/15 bg-white px-3 py-2 text-xs leading-5 text-danger">{error}</p>}
      </div>
      <TrackingJobStrip jobRuns={jobRuns} />
    </section>
  );
}

function TrackingJobStrip({ jobRuns }: { jobRuns: JobRun[] }) {
  if (jobRuns.length === 0) {
    return (
      <p className="mt-3 rounded-md border border-ink/10 bg-white px-3 py-2 text-xs text-muted">
        暂无日报相关任务记录，可先在“数据状态”手动运行一次。
      </p>
    );
  }
  return (
    <div className="mt-3 flex flex-wrap gap-2">
      {jobRuns.map((run) => (
        <span
          key={run.id}
          className={`inline-flex items-center gap-2 rounded-md border px-2.5 py-1 text-xs ${
            run.status === "failed" ? "border-danger/20 bg-danger/10 text-danger" : "border-pine/20 bg-pine/10 text-pine"
          }`}
          title={run.error || run.message || run.job_name}
        >
          <Clock3 size={13} />
          {run.job_name} · {run.status} · {formatDateTime(run.started_at)}
        </span>
      ))}
    </div>
  );
}

function formatDateTime(value: string) {
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone: "Asia/Shanghai"
  }).format(new Date(value));
}

function formatMetricValue(value: string | number) {
  if (typeof value === "number") {
    return Number.isInteger(value) ? value.toString() : value.toFixed(2);
  }
  return value;
}
