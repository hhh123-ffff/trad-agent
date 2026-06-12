import { AlertTriangle, Database, Eye, FilterX, Rocket, Users } from "lucide-react";

import type { ObservationSummary, StealthCandidate } from "@/lib/types";

type FunnelKey = "data" | "observe" | "launch" | "exclude" | "pool";

type StageBucket = "observe" | "launch" | "risk" | "data_gap" | "other";

type FunnelCard = {
  key: FunnelKey;
  title: string;
  value: number;
  detail: string;
  icon: typeof Database;
  tone: string;
};

const MOJIBAKE_STAGES = {
  observe: ["娼滀紡", "瑙傚療"],
  launch: ["鍚姩", "纭"],
  risk: ["杩囩儹", "鎺掗櫎"],
  dataGap: ["鏁版嵁", "涓嶈冻"]
};

export function CandidateFunnel({
  candidates,
  observationSummary
}: {
  candidates: StealthCandidate[];
  observationSummary?: ObservationSummary;
}) {
  const stageCounts = candidates.reduce<Record<StageBucket, number>>(
    (acc, candidate) => {
      const bucket = classifyStage(String(candidate.stage));
      acc[bucket] += 1;
      return acc;
    },
    { observe: 0, launch: 0, risk: 0, data_gap: 0, other: 0 }
  );

  const sourcedCandidates = candidates.filter((candidate) => candidate.source_ids.length > 0).length;
  const exclusionCount = stageCounts.risk + stageCounts.data_gap;
  const shortTermCount = candidates.filter((candidate) => candidate.strategy_horizon === "短线").length;
  const midLongCount = candidates.filter((candidate) => candidate.strategy_horizon === "中长线").length;
  const cards: FunnelCard[] = [
    {
      key: "data",
      title: "数据可用",
      value: sourcedCandidates || candidates.length,
      detail: `最新扫描候选 ${candidates.length} 只`,
      icon: Database,
      tone: "border-ink/10 bg-white text-ink"
    },
    {
      key: "observe",
      title: "潜伏观察",
      value: stageCounts.observe,
      detail: `观察池继续跟踪 ${observationSummary?.continue_count ?? 0} 只`,
      icon: Eye,
      tone: "border-pine/20 bg-pine/10 text-pine"
    },
    {
      key: "launch",
      title: "启动确认",
      value: stageCounts.launch,
      detail: `观察池启动记录 ${observationSummary?.activation_count ?? 0} 条`,
      icon: Rocket,
      tone: "border-signal/25 bg-signal/10 text-signal"
    },
    {
      key: "exclude",
      title: "风险/缺口排除",
      value: exclusionCount,
      detail: `过热 ${stageCounts.risk} 只，数据不足 ${stageCounts.data_gap} 只`,
      icon: FilterX,
      tone: "border-danger/20 bg-danger/10 text-danger"
    },
    {
      key: "pool",
      title: "观察池",
      value: observationSummary?.total ?? candidates.filter((candidate) => candidate.observed).length,
      detail: `短线 ${shortTermCount} 只，中长线 ${midLongCount} 只`,
      icon: Users,
      tone: "border-saffron/35 bg-saffron/10 text-[#8a5a12]"
    }
  ];

  return (
    <section className="rounded-lg border border-ink/10 bg-paper/60 p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-xs font-semibold text-pine">候选漏斗</p>
          <h3 className="mt-1 text-lg font-semibold">盘后候选证据流</h3>
        </div>
        {stageCounts.other > 0 && (
          <span className="inline-flex items-center gap-1 rounded-md border border-saffron/35 bg-white px-2 py-1 text-xs text-[#8a5a12]">
            <AlertTriangle size={13} />
            {stageCounts.other} 个未知阶段
          </span>
        )}
      </div>
      <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-5">
        {cards.map((card) => (
          <FunnelSummaryCard key={card.key} card={card} />
        ))}
      </div>
    </section>
  );
}

function FunnelSummaryCard({ card }: { card: FunnelCard }) {
  const Icon = card.icon;
  return (
    <article className="rounded-lg border border-ink/10 bg-white p-3">
      <div className="flex items-start justify-between gap-3">
        <span className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-md border ${card.tone}`}>
          <Icon size={17} />
        </span>
        <span className="text-2xl font-semibold leading-none">{card.value}</span>
      </div>
      <h4 className="mt-3 text-sm font-semibold leading-5">{card.title}</h4>
      <p className="mt-2 break-words text-xs leading-5 text-muted">{card.detail}</p>
    </article>
  );
}

function classifyStage(stage: string): StageBucket {
  const normalized = stage.toLowerCase();
  if (includesAny(stage, ["潜伏", "观察", ...MOJIBAKE_STAGES.observe]) || normalized.includes("observe")) {
    return "observe";
  }
  if (includesAny(stage, ["启动", "确认", ...MOJIBAKE_STAGES.launch]) || normalized.includes("launch") || normalized.includes("activation")) {
    return "launch";
  }
  if (includesAny(stage, ["过热", "排除", "风险", ...MOJIBAKE_STAGES.risk]) || normalized.includes("risk") || normalized.includes("exclude")) {
    return "risk";
  }
  if (includesAny(stage, ["数据", "不足", "缺口", ...MOJIBAKE_STAGES.dataGap]) || normalized.includes("data")) {
    return "data_gap";
  }
  return "other";
}

function includesAny(value: string, patterns: string[]) {
  return patterns.some((pattern) => value.includes(pattern));
}
