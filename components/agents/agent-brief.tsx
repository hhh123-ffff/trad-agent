import { Bot, CheckCircle2, ShieldAlert } from "lucide-react";

import type { AgentRunDetail } from "@/lib/types";

export function AgentBrief({ detail }: { detail?: AgentRunDetail }) {
  const artifact = detail?.artifacts[0];
  const summary = textValue(artifact?.content.summary) || detail?.run.summary || "";
  const warnings = stringList(artifact?.content.warnings);

  return (
    <section className="panel overflow-hidden rounded-lg">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-ink/10 px-5 py-4">
        <div className="flex items-center gap-3">
          <span className="flex h-9 w-9 items-center justify-center rounded-md bg-signal/10 text-signal">
            <Bot size={18} />
          </span>
          <div>
            <p className="text-xs font-semibold text-signal">Agent 研究层</p>
            <h3 className="text-base font-semibold">{artifact?.title || "盘后研究简报"}</h3>
          </div>
        </div>
        <span className={`rounded-md border px-2.5 py-1 text-xs font-semibold ${runStatusClass(detail?.run.status)}`}>
          {detail?.run.status || "尚未运行"}
        </span>
      </header>
      <div className="grid grid-cols-1 xl:grid-cols-[1.35fr_0.65fr]">
        <div className="border-b border-ink/10 px-5 py-4 xl:border-b-0 xl:border-r">
          <p className="text-sm leading-7 text-ink">
            {summary || "运行盘后研究 Agent 后，这里会显示基于确定性日报、公告摘要和候选指标整理的只读研究简报。"}
          </p>
          {warnings.length > 0 && (
            <div className="mt-4 space-y-2">
              {warnings.map((warning) => (
                <p key={warning} className="flex gap-2 text-xs leading-5 text-saffron">
                  <ShieldAlert className="mt-0.5 shrink-0" size={14} />
                  {warning}
                </p>
              ))}
            </div>
          )}
        </div>
        <div className="px-5 py-4">
          <p className="text-xs font-semibold text-muted">运行审计</p>
          <div className="mt-3 space-y-2">
            <AuditLine label="模型调用" value={detail ? `${detail.run.calls_used} 次` : "--"} />
            <AuditLine label="Token" value={detail ? String(detail.run.tokens_used) : "--"} />
            <AuditLine label="步骤" value={detail ? `${detail.steps.length} 个` : "--"} />
            <AuditLine label="来源" value={artifact ? `${artifact.source_ids.length} 个` : "--"} />
          </div>
        </div>
      </div>
    </section>
  );
}

function AuditLine({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-3 border-b border-ink/10 pb-2 text-xs last:border-b-0 last:pb-0">
      <span className="flex items-center gap-2 text-muted"><CheckCircle2 size={13} className="text-pine" />{label}</span>
      <span className="font-semibold text-ink">{value}</span>
    </div>
  );
}

function textValue(value: unknown) {
  return typeof value === "string" ? value : "";
}

function stringList(value: unknown) {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

function runStatusClass(status?: string) {
  if (status === "completed") return "border-pine/20 bg-pine/10 text-pine";
  if (status === "failed") return "border-danger/20 bg-danger/10 text-danger";
  if (status === "running") return "border-signal/20 bg-signal/10 text-signal";
  return "border-saffron/30 bg-saffron/10 text-saffron";
}
