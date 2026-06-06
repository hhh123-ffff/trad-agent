import { PlayCircle, Target } from "lucide-react";

import { AgentBrief } from "@/components/agents/agent-brief";
import { DataSourceStatusPanel } from "@/components/data-sources/data-source-status";
import { CandidateFunnel } from "@/components/replay/candidate-funnel";
import { DailyReportCard } from "@/components/replay/daily-report";
import { InformationSummaryPanel } from "@/components/replay/information-summary";
import { PostMarketPipeline } from "@/components/replay/job-pipeline";
import type { AgentRunDetail, AgentStatusResponse, DailyTrackingReport, JobRun, ObservationSummary, ReplayReport, StealthCandidate } from "@/lib/types";

export function ReplayView({
  replay,
  trackingDaily,
  jobRuns,
  trackingError,
  candidates,
  observationSummary,
  agents,
  agentRunDetail
}: {
  replay: ReplayReport;
  trackingDaily?: DailyTrackingReport;
  jobRuns: JobRun[];
  trackingError?: string;
  candidates: StealthCandidate[];
  observationSummary?: ObservationSummary;
  agents?: AgentStatusResponse;
  agentRunDetail?: AgentRunDetail;
}) {
  const strategyCandidates = candidates.filter((candidate) => candidate.metrics.strategy_profile === "mainboard_volume_price");
  const launchCount = strategyCandidates.filter((candidate) => String(candidate.stage).includes("启动")).length;

  return (
    <section className="space-y-5">
      <div className="panel rounded-lg p-5">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="flex min-w-0 items-center gap-3">
            <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-pine/10 text-pine">
              <PlayCircle size={18} />
            </span>
            <div className="min-w-0">
              <p className="text-xs font-semibold text-pine">盘后工作台</p>
              <h2 className="text-lg font-semibold">盘后复盘</h2>
            </div>
          </div>
          <span className="rounded-md border border-ink/10 bg-white px-2.5 py-1 text-xs text-muted">{replay.trading_day}</span>
        </div>

        <div className="mt-4 max-w-4xl">
          <h1 className="text-xl font-semibold leading-8">{replay.headline}</h1>
          <p className="mt-2 text-sm leading-6 text-muted">{replay.market_summary}</p>
        </div>
      </div>

      <PostMarketPipeline jobRuns={jobRuns} />
      <DailyReportCard trackingDaily={trackingDaily} trackingError={trackingError} jobRuns={jobRuns} />
      <AgentBrief detail={agentRunDetail} />

      <section className="panel rounded-lg p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <span className="flex h-9 w-9 items-center justify-center rounded-md bg-pine/10 text-pine">
              <Target size={18} />
            </span>
            <div>
              <p className="text-xs font-semibold text-pine">主板量价启动摘要</p>
              <h3 className="mt-1 text-base font-semibold">候选 {strategyCandidates.length} 个，启动确认 {launchCount} 个</h3>
            </div>
          </div>
          <a
            href="#stealth"
            className="inline-flex min-h-9 items-center rounded-md border border-pine/25 bg-pine/5 px-3 text-sm font-semibold text-pine transition hover:bg-pine/10"
          >
            进入潜伏挖掘
          </a>
        </div>
      </section>

      <div className="grid grid-cols-1 gap-5 xl:grid-cols-[0.9fr_1.1fr]">
        <InformationSummaryPanel trackingDaily={trackingDaily} />
        <CandidateFunnel candidates={candidates} observationSummary={observationSummary} />
      </div>

      <div className="grid grid-cols-1 gap-5 xl:grid-cols-[1fr_0.86fr]">
        <section className="panel rounded-lg p-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <p className="text-xs font-semibold text-pine">分时窗口</p>
              <h3 className="mt-1 text-lg font-semibold">错过信号回放</h3>
            </div>
            <span className="text-xs text-muted">{replay.sections.length} 个窗口</span>
          </div>

          <div className="mt-4 grid grid-cols-1 gap-3 lg:grid-cols-2">
            {replay.sections.map((section) => (
              <article key={section.window} className="rounded-lg border border-ink/10 bg-white p-4">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <span className="rounded-md bg-ink px-2.5 py-1 text-xs font-semibold text-white">{section.window}</span>
                  <span className="text-xs text-muted">{section.missed_signals.length} 条信号</span>
                </div>
                <h3 className="mt-3 text-base font-semibold">{section.title}</h3>
                <p className="mt-2 text-sm leading-6 text-muted">{section.summary}</p>
              </article>
            ))}
          </div>
        </section>

        <DataSourceStatusPanel statuses={agents?.data_source_statuses ?? []} />
      </div>
    </section>
  );
}
