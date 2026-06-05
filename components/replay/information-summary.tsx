import { AlertTriangle, Megaphone, Newspaper, Tags } from "lucide-react";

import type { AnnouncementItem, DailyTrackingReport, NewsItem } from "@/lib/types";

type InformationItem = (NewsItem | AnnouncementItem) & { event_type: "news" | "announcement" | string };

type SymbolBucket = {
  symbol: string;
  total: number;
  news: number;
  announcements: number;
  highImportance: number;
  latestTitle: string;
};

export function InformationSummaryPanel({ trackingDaily }: { trackingDaily?: DailyTrackingReport }) {
  const news = trackingDaily?.news ?? [];
  const announcements = trackingDaily?.announcements ?? [];
  const items: InformationItem[] = [
    ...news.map((item) => ({ ...item, event_type: "news" })),
    ...announcements.map((item) => ({ ...item, event_type: "announcement" }))
  ].sort((a, b) => new Date(b.published_at).getTime() - new Date(a.published_at).getTime());
  const highImportance = items.filter((item) => item.importance === "critical" || item.importance === "high").length;
  const sourceIds = Array.from(new Set(items.map((item) => item.source_id).filter(Boolean)));
  const symbolBuckets = buildSymbolBuckets(items);

  return (
    <section className="mt-5 rounded-lg border border-ink/10 bg-paper/60 p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-xs font-semibold text-pine">消息统计</p>
          <h3 className="mt-1 text-lg font-semibold">新闻与公告复盘</h3>
        </div>
        {items.length === 0 && (
          <span className="inline-flex items-center gap-1 rounded-md border border-saffron/35 bg-white px-2 py-1 text-xs text-[#8a5a12]">
            <AlertTriangle size={13} />
            数据缺口
          </span>
        )}
      </div>

      <div className="mt-4 grid grid-cols-2 gap-3 md:grid-cols-4">
        <MetricTile icon={Newspaper} label="新闻" value={news.length} />
        <MetricTile icon={Megaphone} label="公告" value={announcements.length} />
        <MetricTile icon={AlertTriangle} label="高重要性" value={highImportance} />
        <MetricTile icon={Tags} label="涉及标的" value={symbolBuckets.length} />
      </div>

      {items.length === 0 ? (
        <p className="mt-3 rounded-md border border-saffron/30 bg-white px-3 py-2 text-xs leading-5 text-[#8a5a12]">
          暂无已写入的新闻或公告。可以先在数据状态页运行公告新闻任务，或导入已授权的信息源摘要。
        </p>
      ) : (
        <div className="mt-4 grid grid-cols-1 gap-3 lg:grid-cols-[0.9fr_1.1fr]">
          <div className="rounded-lg border border-ink/10 bg-white p-3">
            <h4 className="text-sm font-semibold">涉及标的</h4>
            <div className="mt-3 space-y-2">
              {symbolBuckets.slice(0, 6).map((bucket) => (
                <div key={bucket.symbol} className="rounded-md border border-ink/10 bg-paper px-3 py-2">
                  <div className="flex items-center justify-between gap-3">
                    <span className="text-sm font-semibold">{bucket.symbol}</span>
                    <span className="text-xs text-muted">{bucket.total} 条</span>
                  </div>
                  <p className="mt-1 truncate text-xs text-muted" title={bucket.latestTitle}>
                    新闻 {bucket.news} / 公告 {bucket.announcements} / 高重要性 {bucket.highImportance}
                  </p>
                </div>
              ))}
            </div>
          </div>

          <div className="rounded-lg border border-ink/10 bg-white p-3">
            <h4 className="text-sm font-semibold">最新条目</h4>
            <div className="mt-3 space-y-2">
              {items.slice(0, 5).map((item) => (
                <div key={item.id} className="rounded-md border border-ink/10 bg-paper px-3 py-2">
                  <div className="flex flex-wrap items-center gap-2 text-[11px] text-muted">
                    <span>{item.event_type === "announcement" ? "公告" : "新闻"}</span>
                    <span>{item.importance}</span>
                    {item.symbol && <span>{item.symbol}</span>}
                  </div>
                  <p className="mt-1 line-clamp-2 text-sm font-semibold leading-5">{item.title}</p>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {sourceIds.length > 0 && <p className="mt-3 break-words text-xs text-muted">来源：{sourceIds.join(", ")}</p>}
    </section>
  );
}

function MetricTile({
  icon: Icon,
  label,
  value
}: {
  icon: typeof Newspaper;
  label: string;
  value: number;
}) {
  return (
    <div className="rounded-lg border border-ink/10 bg-white p-3">
      <div className="flex items-center justify-between gap-3">
        <span className="flex h-8 w-8 items-center justify-center rounded-md border border-pine/20 bg-pine/10 text-pine">
          <Icon size={15} />
        </span>
        <span className="text-xl font-semibold">{value}</span>
      </div>
      <p className="mt-2 text-xs text-muted">{label}</p>
    </div>
  );
}

function buildSymbolBuckets(items: InformationItem[]) {
  const buckets = new Map<string, SymbolBucket>();
  for (const item of items) {
    if (!item.symbol) continue;
    const current =
      buckets.get(item.symbol) ??
      ({
        symbol: item.symbol,
        total: 0,
        news: 0,
        announcements: 0,
        highImportance: 0,
        latestTitle: item.title
      } satisfies SymbolBucket);
    current.total += 1;
    current.news += item.event_type === "news" ? 1 : 0;
    current.announcements += item.event_type === "announcement" ? 1 : 0;
    current.highImportance += item.importance === "critical" || item.importance === "high" ? 1 : 0;
    current.latestTitle ||= item.title;
    buckets.set(item.symbol, current);
  }
  return Array.from(buckets.values()).sort((a, b) => b.total - a.total || b.highImportance - a.highImportance);
}
