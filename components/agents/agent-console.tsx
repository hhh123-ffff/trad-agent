import { Bot, Check, Clock3, PlayCircle, RefreshCcw, ShieldAlert, X } from "lucide-react";

import type { AgentAction, AgentRun, AgentRunDetail, AgentUsageSummary } from "@/lib/types";

export function AgentConsole({
  runs,
  detail,
  actions,
  usage,
  error,
  onRun,
  onRefresh,
  onApprove,
  onReject
}: {
  runs: AgentRun[];
  detail?: AgentRunDetail;
  actions: AgentAction[];
  usage?: AgentUsageSummary;
  error?: string;
  onRun: () => void;
  onRefresh: () => void;
  onApprove: (actionId: string) => void;
  onReject: (actionId: string) => void;
}) {
  const latest = detail?.run ?? runs[0];
  const usagePercent = usage ? Math.min(100, Math.round((usage.calls_used_today / Math.max(usage.daily_call_limit, 1)) * 100)) : 0;

  return (
    <section className="panel overflow-hidden rounded-lg">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-ink/10 px-5 py-4">
        <div className="flex min-w-0 items-center gap-3">
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-pine/10 text-pine">
            <Bot size={18} />
          </span>
          <div className="min-w-0">
            <p className="text-xs font-semibold text-pine">受控盘后研究</p>
            <h2 className="text-lg font-semibold">Agent 控制台</h2>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={onRefresh}
            className="inline-flex h-9 w-9 items-center justify-center rounded-md border border-ink/10 bg-white text-muted transition hover:border-pine/30 hover:text-pine"
            title="刷新 Agent 状态"
          >
            <RefreshCcw size={15} />
          </button>
          <button
            type="button"
            onClick={onRun}
            className="inline-flex min-h-9 items-center gap-2 rounded-md bg-pine px-3 text-xs font-semibold text-white transition hover:bg-[#0b514a]"
          >
            <PlayCircle size={15} />
            运行盘后 Agent
          </button>
        </div>
      </header>

      <div className="grid grid-cols-2 border-b border-ink/10 bg-[#f8fafb] sm:grid-cols-4">
        <ConsoleMetric label="模型连接" value={usage?.configured ? usage.model || "已配置" : "未配置"} tone={usage?.configured ? "good" : "warning"} />
        <ConsoleMetric label="今日调用" value={usage ? `${usage.calls_used_today}/${usage.daily_call_limit}` : "--"} />
        <ConsoleMetric label="最新运行" value={latest?.status ?? "暂无"} tone={latest?.status === "completed" ? "good" : latest ? "warning" : undefined} />
        <ConsoleMetric label="待审批" value={String(actions.length)} tone={actions.length ? "warning" : "good"} />
      </div>

      {error && (
        <div className="flex gap-2 border-b border-danger/20 bg-danger/5 px-5 py-3 text-xs leading-5 text-danger">
          <ShieldAlert className="mt-0.5 shrink-0" size={15} />
          {error}
        </div>
      )}

      <div className="grid grid-cols-1 xl:grid-cols-[1.35fr_0.85fr]">
        <div className="border-b border-ink/10 px-5 py-4 xl:border-b-0 xl:border-r">
          <div className="flex items-center justify-between gap-3">
            <h3 className="text-sm font-semibold">最近步骤</h3>
            <span className="text-xs text-muted">{latest ? formatDateTime(latest.started_at) : "等待首次运行"}</span>
          </div>
          <div className="mt-4">
            {(detail?.steps ?? []).map((step, index) => (
              <div key={step.id} className="relative flex gap-3 pb-4 last:pb-0">
                {index < (detail?.steps.length ?? 0) - 1 && <span className="absolute left-[7px] top-5 h-[calc(100%-12px)] w-px bg-ink/10" />}
                <span className={`mt-1.5 h-3.5 w-3.5 shrink-0 rounded-full border-2 bg-white ${statusDot(step.status)}`} />
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <p className="text-sm font-semibold">{step.agent_name}</p>
                    <span className={`text-xs font-medium ${statusText(step.status)}`}>{step.status}</span>
                  </div>
                  <p className="mt-1 break-words text-xs leading-5 text-muted">
                    {step.error || stepSummary(step.output) || "结构化步骤已完成并留痕。"}
                  </p>
                </div>
              </div>
            ))}
            {!detail?.steps.length && <p className="text-sm leading-6 text-muted">运行后会在这里显示数据质量、公告、候选、观察、编辑和合规步骤。</p>}
          </div>
          <div className="mt-5 border-t border-ink/10 pt-4">
            <div className="flex items-center justify-between text-xs text-muted">
              <span>每日模型预算</span>
              <span>{usage ? `${usage.calls_remaining_today} 次剩余` : "未读取"}</span>
            </div>
            <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-steel">
              <div className="h-full rounded-full bg-signal transition-all" style={{ width: `${usagePercent}%` }} />
            </div>
          </div>
        </div>

        <div className="px-5 py-4">
          <div className="flex items-center justify-between gap-3">
            <h3 className="text-sm font-semibold">人工审批队列</h3>
            <span className="text-xs text-muted">删除观察项需确认</span>
          </div>
          <div className="mt-3 divide-y divide-ink/10">
            {actions.map((action) => (
              <article key={action.id} className="py-3 first:pt-0 last:pb-0">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="text-sm font-semibold">{action.symbol || action.action_type}</p>
                    <p className="mt-1 text-xs leading-5 text-muted">{action.rationale || "Agent 请求人工确认该动作。"}</p>
                  </div>
                  <div className="flex shrink-0 gap-1.5">
                    <button
                      type="button"
                      onClick={() => onApprove(action.id)}
                      className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-pine/20 bg-pine/5 text-pine transition hover:bg-pine/10"
                      title="批准并执行"
                    >
                      <Check size={15} />
                    </button>
                    <button
                      type="button"
                      onClick={() => onReject(action.id)}
                      className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-danger/20 bg-danger/5 text-danger transition hover:bg-danger/10"
                      title="拒绝"
                    >
                      <X size={15} />
                    </button>
                  </div>
                </div>
              </article>
            ))}
            {actions.length === 0 && (
              <div className="flex gap-2 py-3 text-xs leading-5 text-muted">
                <Clock3 className="mt-0.5 shrink-0 text-pine" size={15} />
                当前没有待审批动作。Agent 可以自动新增或更新候选观察，但不会自动删除。
              </div>
            )}
          </div>
        </div>
      </div>
    </section>
  );
}

function ConsoleMetric({ label, value, tone }: { label: string; value: string; tone?: "good" | "warning" }) {
  const color = tone === "good" ? "text-pine" : tone === "warning" ? "text-saffron" : "text-ink";
  return (
    <div className="border-b border-r border-ink/10 px-4 py-3 last:border-r-0 sm:border-b-0">
      <p className="text-[11px] text-muted">{label}</p>
      <p className={`mt-1 truncate text-sm font-semibold ${color}`} title={value}>{value}</p>
    </div>
  );
}

function stepSummary(output: Record<string, unknown>) {
  return typeof output.summary === "string" ? output.summary : "";
}

function statusDot(status: string) {
  if (status === "completed") return "border-pine";
  if (status === "failed") return "border-danger";
  return "border-saffron";
}

function statusText(status: string) {
  if (status === "completed") return "text-pine";
  if (status === "failed") return "text-danger";
  return "text-saffron";
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
