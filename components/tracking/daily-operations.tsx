"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  Bell,
  Check,
  CheckCircle2,
  CircleDashed,
  Clock3,
  PlayCircle,
  RefreshCcw,
  RotateCcw,
  XCircle
} from "lucide-react";

import {
  loadAdminJobRunDetail,
  loadAdminNotifications,
  markAdminNotificationRead,
  rerunAdminJobStep
} from "@/lib/api";
import { detailedPostMarketPipeline, jobRunFreshness, latestPostMarketRun, type PipelineStatus } from "@/lib/job-status";
import type { AppNotification, JobRun, JobRunDetail } from "@/lib/types";

export function DailyOperations({
  jobRuns,
  onRunJob
}: {
  jobRuns: JobRun[];
  onRunJob: (jobName: string) => void;
}) {
  const latest = useMemo(() => latestPostMarketRun(jobRuns), [jobRuns]);
  const [detail, setDetail] = useState<JobRunDetail | null>(null);
  const [notifications, setNotifications] = useState<AppNotification[]>([]);
  const [error, setError] = useState<string>();
  const [loading, setLoading] = useState(false);
  const [rerunning, setRerunning] = useState<string>();

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [nextDetail, nextNotifications] = await Promise.all([
        latest ? loadAdminJobRunDetail(latest.id) : Promise.resolve(null),
        loadAdminNotifications({ limit: 12 })
      ]);
      setDetail(nextDetail);
      setNotifications(nextNotifications);
      setError(undefined);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "无法读取今日闭环状态。");
    } finally {
      setLoading(false);
    }
  }, [latest]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const steps = detailedPostMarketPipeline(detail);
  const freshness = jobRunFreshness(detail?.run ?? latest);
  const targetDay = String(detail?.run.affected_scope.trading_day ?? freshness?.checks[0]?.expected_date ?? "等待运行");

  async function rerun(stepName: string) {
    if (!detail) return;
    setRerunning(stepName);
    try {
      setDetail(await rerunAdminJobStep(detail.run.id, stepName));
      setError(undefined);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "步骤重跑失败。");
    } finally {
      setRerunning(undefined);
    }
  }

  async function markRead(notificationId: string) {
    try {
      const updated = await markAdminNotificationRead(notificationId);
      setNotifications((items) => items.map((item) => (item.id === updated.id ? updated : item)));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "通知状态更新失败。");
    }
  }

  return (
    <section className="panel overflow-hidden rounded-lg">
      <header className="flex flex-wrap items-start justify-between gap-4 border-b border-ink/10 px-5 py-4">
        <div>
          <div className="flex items-center gap-2 text-xs font-semibold text-pine">
            <Clock3 size={14} />
            今日闭环
          </div>
          <div className="mt-2 flex flex-wrap items-center gap-3">
            <h2 className="text-lg font-semibold text-ink">{targetDay}</h2>
            <StatusBadge status={detail?.run.status ?? latest?.status ?? "queued"} />
            <span className={freshnessClass(freshness?.status)}>{freshnessLabel(freshness?.status)}</span>
          </div>
          <p className="mt-2 max-w-3xl text-xs leading-5 text-muted">
            {detail?.run.message ?? latest?.message ?? "运行一次盘后闭环后，这里会显示六个步骤、数据新鲜度和恢复入口。"}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => void refresh()}
            disabled={loading}
            title="刷新闭环状态"
            className="inline-flex h-9 w-9 items-center justify-center rounded-md border border-ink/10 bg-white text-muted transition hover:border-pine/30 hover:text-pine disabled:opacity-50"
          >
            <RefreshCcw size={15} className={loading ? "animate-spin" : ""} />
          </button>
          <button
            type="button"
            onClick={() => onRunJob("post_market_replay")}
            className="inline-flex min-h-9 items-center gap-2 rounded-md bg-pine px-3 text-xs font-semibold text-white transition hover:bg-pine/90"
          >
            <PlayCircle size={15} />
            运行今日闭环
          </button>
        </div>
      </header>

      {error && (
        <div className="flex items-start gap-2 border-b border-danger/20 bg-danger/5 px-5 py-3 text-xs leading-5 text-danger">
          <AlertTriangle size={15} className="mt-0.5 shrink-0" />
          <span>{error} 请确认 API、Postgres 和 Redis 已启动后重试。</span>
        </div>
      )}

      <div className="grid grid-cols-1 xl:grid-cols-[minmax(0,1.5fr)_minmax(280px,0.65fr)]">
        <div className="min-w-0 px-5 py-2">
          {steps.map((step, index) => (
            <div key={step.key} className="grid grid-cols-[26px_minmax(0,1fr)_auto] gap-3 border-b border-ink/8 py-4 last:border-b-0">
              <div className="flex flex-col items-center">
                <StepIcon status={step.status} />
                {index < steps.length - 1 && <span className="mt-1 h-full w-px bg-ink/10" />}
              </div>
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <h3 className="text-sm font-semibold text-ink">{step.label}</h3>
                  <span className={stepStatusClass(step.status)}>{statusLabel(step.status)}</span>
                  {step.errorCode && <span className="text-[11px] text-danger">{step.errorCode}</span>}
                </div>
                <p className="mt-1 break-words text-xs leading-5 text-muted">{step.detail}</p>
                <div className="mt-2 flex flex-wrap gap-3 text-[11px] text-muted">
                  <span>尝试 {step.attempts || 0} 次</span>
                  <span>耗时 {formatDuration(step.durationMs)}</span>
                </div>
              </div>
              <div className="flex items-start">
                {step.retryable && (
                  <button
                    type="button"
                    onClick={() => void rerun(step.key)}
                    disabled={rerunning === step.key}
                    title={`重跑${step.label}`}
                    className="inline-flex h-8 items-center gap-1.5 rounded-md border border-saffron/30 bg-saffron/5 px-2.5 text-xs font-semibold text-saffron transition hover:bg-saffron/10 disabled:opacity-50"
                  >
                    <RotateCcw size={13} className={rerunning === step.key ? "animate-spin" : ""} />
                    重跑
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>

        <aside className="border-t border-ink/10 bg-ink/[0.018] px-4 py-4 xl:border-l xl:border-t-0">
          <div className="flex items-center justify-between gap-3">
            <div className="flex items-center gap-2 text-sm font-semibold text-ink">
              <Bell size={15} className="text-pine" />
              运行通知
            </div>
            <span className="text-[11px] text-muted">{notifications.filter((item) => !item.read_at).length} 条未读</span>
          </div>
          <div className="mt-3 divide-y divide-ink/8">
            {notifications.map((notification) => (
              <div key={notification.id} className="py-3 first:pt-0">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <span className={notificationSeverityClass(notification.severity)} />
                      <p className="truncate text-xs font-semibold text-ink">{notification.title}</p>
                    </div>
                    <p className="mt-1 text-[11px] leading-5 text-muted">{notification.message}</p>
                    <p className="mt-1 text-[10px] text-muted">{formatDateTime(notification.created_at)}</p>
                  </div>
                  {!notification.read_at && (
                    <button
                      type="button"
                      onClick={() => void markRead(notification.id)}
                      title="标记已读"
                      className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-muted transition hover:bg-white hover:text-pine"
                    >
                      <Check size={13} />
                    </button>
                  )}
                </div>
              </div>
            ))}
            {notifications.length === 0 && <p className="py-6 text-center text-xs text-muted">暂无运行通知</p>}
          </div>
        </aside>
      </div>
    </section>
  );
}

function StepIcon({ status }: { status: PipelineStatus }) {
  if (status === "completed") return <CheckCircle2 size={17} className="text-pine" />;
  if (status === "failed") return <XCircle size={17} className="text-danger" />;
  if (status === "degraded" || status === "skipped") return <AlertTriangle size={17} className="text-saffron" />;
  if (status === "running") return <RefreshCcw size={17} className="animate-spin text-signal" />;
  return <CircleDashed size={17} className="text-muted" />;
}

function StatusBadge({ status }: { status: JobRun["status"] }) {
  return <span className={jobStatusClass(status)}>{statusLabel(status)}</span>;
}

function statusLabel(status: string) {
  return {
    queued: "排队中",
    pending: "未执行",
    running: "运行中",
    completed: "已完成",
    degraded: "降级完成",
    failed: "失败",
    skipped: "已跳过"
  }[status] ?? status;
}

function jobStatusClass(status: JobRun["status"]) {
  if (status === "completed") return "rounded-md border border-pine/20 bg-pine/10 px-2 py-1 text-xs font-semibold text-pine";
  if (status === "failed") return "rounded-md border border-danger/20 bg-danger/10 px-2 py-1 text-xs font-semibold text-danger";
  if (status === "degraded" || status === "skipped") return "rounded-md border border-saffron/30 bg-saffron/10 px-2 py-1 text-xs font-semibold text-saffron";
  return "rounded-md border border-signal/20 bg-signal/10 px-2 py-1 text-xs font-semibold text-signal";
}

function stepStatusClass(status: PipelineStatus) {
  if (status === "completed") return "rounded border border-pine/20 bg-pine/8 px-1.5 py-0.5 text-[10px] font-semibold text-pine";
  if (status === "failed") return "rounded border border-danger/20 bg-danger/8 px-1.5 py-0.5 text-[10px] font-semibold text-danger";
  if (status === "degraded" || status === "skipped") return "rounded border border-saffron/25 bg-saffron/8 px-1.5 py-0.5 text-[10px] font-semibold text-saffron";
  return "rounded border border-signal/20 bg-signal/8 px-1.5 py-0.5 text-[10px] font-semibold text-signal";
}

function freshnessLabel(status?: string) {
  if (status === "fresh") return "数据新鲜";
  if (status === "stale") return "数据过期";
  if (status === "missing") return "数据缺失";
  return "待检查新鲜度";
}

function freshnessClass(status?: string) {
  if (status === "fresh") return "text-xs font-semibold text-pine";
  if (status === "stale") return "text-xs font-semibold text-saffron";
  if (status === "missing") return "text-xs font-semibold text-danger";
  return "text-xs text-muted";
}

function notificationSeverityClass(severity: AppNotification["severity"]) {
  if (severity === "critical") return "h-2 w-2 shrink-0 rounded-full bg-danger";
  if (severity === "warning") return "h-2 w-2 shrink-0 rounded-full bg-saffron";
  return "h-2 w-2 shrink-0 rounded-full bg-pine";
}

function formatDuration(durationMs: number) {
  if (!durationMs) return "0s";
  return durationMs < 1000 ? `${durationMs}ms` : `${Math.round(durationMs / 1000)}s`;
}

function formatDateTime(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("zh-CN", { hour12: false });
}
