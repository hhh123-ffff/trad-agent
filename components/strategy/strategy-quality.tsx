"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Activity, AlertTriangle, CheckCircle2, FlaskConical, Play, RefreshCcw, ShieldAlert } from "lucide-react";

import {
  loadLatestStrategyBacktest,
  loadStrategyBacktestDetail,
  loadStrategyBacktestSignals,
  loadStrategyLiveOutcomes,
  runStrategyBacktest
} from "@/lib/api";
import type {
  StrategyBacktestFunnel,
  StrategyBacktestRun,
  StrategyLiveOutcomeSummary,
  StrategySignalOutcome
} from "@/lib/types";

const horizons = ["1d", "3d", "5d", "10d"];

function objectValue(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
}

function numberValue(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function metric(value: unknown, suffix = "") {
  const parsed = numberValue(value);
  return parsed === null ? "--" : `${parsed.toFixed(parsed % 1 === 0 ? 0 : 2)}${suffix}`;
}

function dateText(value: string | null | undefined) {
  return value ? value.slice(0, 10) : "--";
}

function statusTone(status: StrategyBacktestRun["status"] | undefined) {
  if (status === "completed") return "border-pine/25 bg-pine/5 text-pine";
  if (status === "failed") return "border-danger/25 bg-danger/5 text-danger";
  return "border-signal/25 bg-signal/5 text-signal";
}

export function StrategyQuality() {
  const [run, setRun] = useState<StrategyBacktestRun | null>(null);
  const [funnel, setFunnel] = useState<StrategyBacktestFunnel | null>(null);
  const [signals, setSignals] = useState<StrategySignalOutcome[]>([]);
  const [live, setLive] = useState<StrategyLiveOutcomeSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setError(null);
    const [latestResult, liveResult] = await Promise.allSettled([
      loadLatestStrategyBacktest(),
      loadStrategyLiveOutcomes()
    ]);
    if (liveResult.status === "fulfilled") setLive(liveResult.value);
    if (latestResult.status === "rejected") {
      if (!latestResult.reason?.message?.includes("404")) setError(latestResult.reason?.message ?? "策略质量数据加载失败");
      setRun(null);
      setFunnel(null);
      setSignals([]);
      setLoading(false);
      return;
    }
    const latest = latestResult.value;
    setRun(latest);
    const [detailResult, signalsResult] = await Promise.allSettled([
      loadStrategyBacktestDetail(latest.id),
      loadStrategyBacktestSignals(latest.id, { primaryOnly: true, limit: 12 })
    ]);
    if (detailResult.status === "fulfilled") {
      setRun(detailResult.value.run);
      setFunnel(detailResult.value.funnel);
    }
    if (signalsResult.status === "fulfilled") setSignals(signalsResult.value);
    setLoading(false);
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    if (run?.status !== "queued" && run?.status !== "running") return;
    const timer = window.setInterval(() => void refresh(), 2500);
    return () => window.clearInterval(timer);
  }, [refresh, run?.status]);

  async function startBacktest() {
    setRunning(true);
    setError(null);
    try {
      const created = await runStrategyBacktest({ repeat_days: 3 });
      setRun(created);
      setFunnel(null);
      setSignals([]);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "回测任务创建失败");
    } finally {
      setRunning(false);
    }
  }

  const summary = objectValue(run?.summary);
  const horizonSummary = objectValue(summary.horizons);
  const fiveDay = objectValue(horizonSummary["5d"]);
  const stageSummary = objectValue(summary.stages);
  const funnelRows = useMemo(
    () =>
      Object.entries(funnel?.counts ?? {}).sort((left, right) => right[1] - left[1]).slice(0, 8),
    [funnel]
  );
  const lowConfidence = summary.confidence === "low";
  const isActive = run?.status === "queued" || run?.status === "running";

  return (
    <section className="mb-5 min-w-0 max-w-full border-b border-ink/10 pb-5">
      <div className="flex flex-col justify-between gap-4 lg:flex-row lg:items-start">
        <div>
          <div className="flex items-center gap-2 text-sm font-semibold text-ink">
            <FlaskConical size={17} className="text-pine" />
            策略质量审计
          </div>
          <p className="mt-1 max-w-3xl text-xs leading-5 text-muted">
            仅评估沪深主板，排除 688、300/301、北交所与 ST；历史回放采用下一交易日开盘作为入场基准，真实信号单独跟踪。
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => void refresh()}
            disabled={loading}
            title="刷新策略质量"
            className="inline-flex min-h-9 items-center gap-2 rounded-md border border-ink/10 bg-white px-3 text-xs font-semibold text-muted transition hover:border-pine/30 hover:text-pine disabled:opacity-50"
          >
            <RefreshCcw size={14} className={loading ? "animate-spin" : ""} />
            刷新
          </button>
          <button
            type="button"
            onClick={() => void startBacktest()}
            disabled={running || isActive}
            className="inline-flex min-h-9 items-center gap-2 rounded-md bg-pine px-3 text-xs font-semibold text-white transition hover:bg-[#0b514a] disabled:opacity-50"
          >
            <Play size={14} className={isActive ? "animate-pulse" : ""} />
            {isActive ? "回放中" : "运行本地回放"}
          </button>
        </div>
      </div>

      {error && (
        <div className="mt-4 flex items-start gap-2 border-l-2 border-danger bg-danger/5 px-3 py-2 text-xs leading-5 text-danger">
          <AlertTriangle size={15} className="mt-0.5 shrink-0" />
          <span>{error}。请确认 API、Postgres 与 Redis 已启动后重试。</span>
        </div>
      )}

      {!run && !loading ? (
        <div className="mt-4 flex flex-col justify-between gap-3 border-y border-ink/10 bg-paper/70 px-3 py-4 sm:flex-row sm:items-center">
          <div>
            <p className="text-sm font-semibold text-ink">尚无历史回放结果</p>
            <p className="mt-1 text-xs text-muted">运行一次本地回放后，这里会展示周期表现、阶段差异和候选漏斗。</p>
          </div>
          <span className="text-xs font-semibold text-signal">仅使用已写入本地数据库的日线</span>
        </div>
      ) : null}

      {run && (
        <>
          <div className="mt-4 flex flex-wrap items-center gap-2 border-y border-ink/10 py-3 text-xs">
            <span className={`rounded-md border px-2 py-1 font-semibold ${statusTone(run.status)}`}>{run.status}</span>
            <span className="text-muted">任务 {run.id.slice(0, 8)}</span>
            <span className="text-muted">{dateText(run.start_date)} 至 {dateText(run.end_date)}</span>
            <span className="text-muted">股票 {run.total_symbols}</span>
            <span className="text-muted">主样本 {run.primary_signals}</span>
            <span className={`font-semibold ${lowConfidence ? "text-amber-700" : "text-pine"}`}>
              置信度 {String(summary.confidence ?? "--")}
            </span>
            <span className="ml-auto text-muted">{run.message}</span>
          </div>

          {isActive && (
            <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-ink/5">
              <div className="h-full bg-pine transition-all duration-500" style={{ width: `${Math.max(2, run.progress * 100)}%` }} />
            </div>
          )}

          <div className="mt-4 grid grid-cols-2 border-y border-ink/10 md:grid-cols-5">
            <QualityMetric label="成熟主样本" value={metric(summary.mature_primary_signals)} />
            <QualityMetric label="5 日中位收益" value={metric(fiveDay.median_close_return_pct, "%")} tone="pine" />
            <QualityMetric label="5 日超额中位数" value={metric(fiveDay.median_excess_return_pct, "%")} tone="signal" />
            <QualityMetric label="5 日跑赢比例" value={metric(fiveDay.outperformance_rate_pct, "%")} tone="signal" />
            <QualityMetric label="5 日不利波动" value={metric(fiveDay.median_mae_pct, "%")} tone="danger" />
          </div>

          <div className="mt-4 grid gap-5 xl:grid-cols-[1.1fr_0.9fr]">
            <div className="min-w-0">
              <div className="flex items-center justify-between">
                <h4 className="text-xs font-semibold text-ink">周期表现</h4>
                <span className="text-[11px] text-muted">收益单位 %</span>
              </div>
              <div className="mt-2 overflow-x-auto border-y border-ink/10">
                <table className="w-full min-w-[620px] text-left text-xs">
                  <thead className="bg-paper text-[11px] text-muted">
                    <tr>
                      <th className="px-2 py-2 font-semibold">周期</th>
                      <th className="px-2 py-2 font-semibold">成熟样本</th>
                      <th className="px-2 py-2 font-semibold">中位收益</th>
                      <th className="px-2 py-2 font-semibold">中位超额</th>
                      <th className="px-2 py-2 font-semibold">跑赢比例</th>
                      <th className="px-2 py-2 font-semibold">MFE / MAE</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-ink/10">
                    {horizons.map((horizon) => {
                      const row = objectValue(horizonSummary[horizon]);
                      return (
                        <tr key={horizon} className="transition hover:bg-pine/5">
                          <td className="px-2 py-2 font-semibold text-ink">{horizon}</td>
                          <td className="px-2 py-2 text-muted">{metric(row.mature_count)}</td>
                          <td className="px-2 py-2 font-semibold text-pine">{metric(row.median_close_return_pct, "%")}</td>
                          <td className="px-2 py-2 text-signal">{metric(row.median_excess_return_pct, "%")}</td>
                          <td className="px-2 py-2 text-muted">{metric(row.outperformance_rate_pct, "%")}</td>
                          <td className="px-2 py-2 text-muted">{metric(row.median_mfe_pct, "%")} / {metric(row.median_mae_pct, "%")}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>

            <div className="grid content-start gap-4">
              <div>
                <h4 className="text-xs font-semibold text-ink">阶段对比</h4>
                <div className="mt-2 divide-y divide-ink/10 border-y border-ink/10">
                  {Object.entries(stageSummary).length ? Object.entries(stageSummary).map(([stage, raw]) => {
                    const row = objectValue(raw);
                    return (
                      <div key={stage} className="grid grid-cols-[1fr_auto_auto] items-center gap-3 py-2 text-xs">
                        <span className="font-semibold text-ink">{stage}</span>
                        <span className="text-muted">{metric(row.primary_signals)} 个样本</span>
                        <span className="font-semibold text-pine">{metric(row.median_5d_close_return_pct, "%")}</span>
                      </div>
                    );
                  }) : <p className="py-3 text-xs text-muted">尚无可比较阶段样本。</p>}
                </div>
              </div>

              <div>
                <h4 className="text-xs font-semibold text-ink">候选漏斗</h4>
                <div className="mt-2 grid grid-cols-2 gap-x-4 border-y border-ink/10 py-2 text-xs">
                  {funnelRows.length ? funnelRows.map(([label, value]) => (
                    <div key={label} className="flex items-center justify-between gap-2 border-b border-ink/5 py-1.5">
                      <span className="truncate text-muted">{label}</span>
                      <span className="font-semibold text-ink">{value}</span>
                    </div>
                  )) : <p className="col-span-2 py-2 text-muted">任务完成后显示漏斗。</p>}
                </div>
              </div>
            </div>
          </div>

          <div className="mt-4 grid min-w-0 gap-5 xl:grid-cols-[1.25fr_0.75fr]">
            <div className="min-w-0">
              <div className="flex items-center justify-between">
                <h4 className="text-xs font-semibold text-ink">近期主样本</h4>
                <span className="text-[11px] text-muted">次日开盘作为结果基准</span>
              </div>
              <div className="mt-2 overflow-x-auto border-y border-ink/10">
                <table className="w-full min-w-[620px] text-left text-xs">
                  <thead className="bg-paper text-[11px] text-muted">
                    <tr>
                      <th className="px-2 py-2 font-semibold">信号日</th>
                      <th className="px-2 py-2 font-semibold">股票</th>
                      <th className="px-2 py-2 font-semibold">阶段 / 分数</th>
                      <th className="px-2 py-2 font-semibold">5 日结果</th>
                      <th className="px-2 py-2 font-semibold">样本状态</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-ink/10">
                    {signals.length ? signals.slice(0, 8).map((signal) => {
                      const result = objectValue(signal.horizon_outcomes["5d"]);
                      return (
                        <tr key={signal.id} className="transition hover:bg-pine/5">
                          <td className="px-2 py-2 text-muted">{signal.signal_date}</td>
                          <td className="px-2 py-2 font-semibold text-ink">{signal.symbol} {signal.name}</td>
                          <td className="px-2 py-2 text-muted">{signal.stage} / {signal.total_score.toFixed(0)}</td>
                          <td className="px-2 py-2 font-semibold text-pine">{metric(result.close_return_pct, "%")}</td>
                          <td className="px-2 py-2 text-muted">{signal.sample_quality || String(result.status ?? "--")}</td>
                        </tr>
                      );
                    }) : (
                      <tr><td colSpan={5} className="px-2 py-4 text-center text-muted">尚无主样本。</td></tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>

            <div className="border-l-0 border-ink/10 xl:border-l xl:pl-5">
              <div className="flex items-center gap-2 text-xs font-semibold text-ink">
                <Activity size={15} className="text-signal" />
                真实信号跟踪
              </div>
              <div className="mt-3 grid grid-cols-2 gap-3">
                <QualityMetric label="真实信号" value={metric(live?.total_signals)} compact />
                <QualityMetric label="成熟样本" value={metric(live?.mature_signals)} compact tone="signal" />
              </div>
              <div className="mt-4 flex items-start gap-2 border-l-2 border-amber-400 bg-amber-50 px-3 py-2 text-xs leading-5 text-amber-900">
                <ShieldAlert size={15} className="mt-0.5 shrink-0" />
                <span>历史回放存在流通市值估算、主题缺口和幸存者偏差。低置信度时只用于检查规则，不形成方向结论。</span>
              </div>
              {run.error && (
                <div className="mt-3 flex items-start gap-2 border-l-2 border-danger bg-danger/5 px-3 py-2 text-xs leading-5 text-danger">
                  <AlertTriangle size={15} className="mt-0.5 shrink-0" />
                  <span>{run.error}</span>
                </div>
              )}
              {run.status === "completed" && (
                <div className="mt-3 flex items-center gap-2 text-xs text-pine">
                  <CheckCircle2 size={15} />
                  回放结果已持久化，可复测和比较。
                </div>
              )}
            </div>
          </div>
        </>
      )}
    </section>
  );
}

function QualityMetric({
  label,
  value,
  tone = "ink",
  compact = false
}: {
  label: string;
  value: string;
  tone?: "ink" | "pine" | "signal" | "danger";
  compact?: boolean;
}) {
  const tones = {
    ink: "text-ink",
    pine: "text-pine",
    signal: "text-signal",
    danger: "text-danger"
  };
  return (
    <div className={`${compact ? "px-0 py-1" : "border-b border-r border-ink/10 px-3 py-3 md:border-b-0"}`}>
      <p className="text-[11px] text-muted">{label}</p>
      <p className={`mt-1 font-semibold ${compact ? "text-lg" : "text-xl"} ${tones[tone]}`}>{value}</p>
    </div>
  );
}
