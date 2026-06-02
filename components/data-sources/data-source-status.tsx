import { CheckCircle2, CircleOff, GitBranch, KeyRound } from "lucide-react";
import type { LucideIcon } from "lucide-react";

import type { DataSourceStatus } from "@/lib/types";

const statusConfig: Record<
  DataSourceStatus["status"],
  {
    label: string;
    icon: LucideIcon;
    tone: string;
  }
> = {
  configured: {
    label: "已配置",
    icon: CheckCircle2,
    tone: "border-pine/20 bg-pine/10 text-pine"
  },
  missing_credentials: {
    label: "缺少凭证",
    icon: KeyRound,
    tone: "border-saffron/35 bg-saffron/10 text-[#8a5a12]"
  },
  fallback: {
    label: "降级兜底",
    icon: GitBranch,
    tone: "border-saffron/35 bg-saffron/10 text-[#8a5a12]"
  },
  not_enabled: {
    label: "未启用",
    icon: CircleOff,
    tone: "border-ink/10 bg-paper text-muted"
  }
};

export function DataSourceStatusPanel({ statuses }: { statuses: DataSourceStatus[] }) {
  if (statuses.length === 0) {
    return null;
  }

  return (
    <section className="rounded-lg border border-ink/10 bg-paper/60 p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-xs font-semibold text-pine">数据源状态</p>
          <h3 className="mt-1 text-lg font-semibold">来源就绪度</h3>
        </div>
        <span className="rounded-md border border-ink/10 bg-white px-2.5 py-1 text-xs text-muted">{statuses.length} 个来源</span>
      </div>
      <div className="mt-4 grid grid-cols-1 gap-3 lg:grid-cols-2">
        {statuses.map((status) => (
          <DataSourceStatusCard key={status.id} status={status} />
        ))}
      </div>
    </section>
  );
}

function DataSourceStatusCard({ status }: { status: DataSourceStatus }) {
  const config = statusConfig[status.status];
  const Icon = config.icon;
  const capabilities = Object.entries(status.capabilities);

  return (
    <article className="rounded-lg border border-ink/10 bg-white p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h4 className="break-words text-sm font-semibold">{status.name}</h4>
          <p className="mt-1 break-words text-xs text-muted">{status.provider}</p>
        </div>
        <span className={`inline-flex shrink-0 items-center gap-1 rounded-md border px-2 py-1 text-xs font-semibold ${config.tone}`}>
          <Icon size={13} />
          {config.label}
        </span>
      </div>
      {capabilities.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-2">
          {capabilities.map(([key, value]) => (
            <span key={key} className="max-w-full break-words rounded-md border border-ink/10 bg-paper px-2 py-1 text-xs text-muted">
              {key}: {value}
            </span>
          ))}
        </div>
      )}
      {status.latest_error && <p className="mt-3 break-words rounded-md border border-danger/15 bg-danger/10 px-3 py-2 text-xs leading-5 text-danger">{status.latest_error}</p>}
      <p className="mt-3 break-words text-xs leading-5 text-muted">{status.next_step}</p>
    </article>
  );
}
