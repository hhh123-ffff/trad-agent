"use client";

import { type FormEvent, useEffect, useMemo, useState } from "react";
import {
  Activity,
  AlertTriangle,
  Bell,
  Bot,
  CalendarClock,
  CheckCircle2,
  Clock3,
  Database,
  FileText,
  LayoutDashboard,
  LineChart,
  Plus,
  PlayCircle,
  Radio,
  RefreshCcw,
  Search,
  ShieldCheck,
  Sparkles,
  Target,
  TrendingDown,
  TrendingUp,
  Trash2
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { DataSourceStatusPanel } from "@/components/data-sources/data-source-status";
import { ReplayView } from "@/components/views/replay-view";
import {
  askAssistant,
  createWatchlistItem,
  deleteStealthObservation,
  deleteWatchlistItem,
  loadAgents,
  loadAdminJobRuns,
  loadDashboard,
  loadLatestStealthScanTask,
  loadPreopen,
  loadReplay,
  loadStealthCandidate,
  loadStealthCandidates,
  loadStealthDiagnostics,
  loadStealthObservationJournal,
  loadStealthObservationSummary,
  loadStealthObservations,
  loadStealthScanFailures,
  loadStealthScanMonitor,
  loadStealthScanTask,
  loadTrackingDaily,
  loadTrackingEvents,
  loadTrackingSnapshots,
  observeStealthCandidate,
  resolveStealthScanFailures,
  retryStealthScanFailures,
  runAdminJob,
  runStealthObservationScan,
  runStealthScan,
  snapshotStealthObservationJournal,
  updateStealthObservation
} from "@/lib/api";
import type {
  AgentStatusResponse,
  AssistantAnswer,
  BriefItem,
  DashboardResponse,
  DailyTrackingReport,
  Importance,
  JobRun,
  MarketEvent,
  MarketSnapshot,
  ObservationItem,
  ObservationJournalEntry,
  ObservationSummary,
  PreopenBrief,
  ReplayReport,
  SectorSnapshot,
  SourceRef,
  StealthCandidate,
  StealthCandidateDetail,
  StealthScanFailure,
  StealthScanMonitor,
  StealthScanTask,
  WatchlistStock
} from "@/lib/types";

type LoadState = {
  dashboard?: DashboardResponse;
  preopen?: PreopenBrief;
  replay?: ReplayReport;
  agents?: AgentStatusResponse;
  stealthCandidates?: StealthCandidate[];
  stealthDiagnostics?: StealthCandidate[];
  stealthObservations?: ObservationItem[];
  stealthObservationSummary?: ObservationSummary;
  stealthObservationJournal?: ObservationJournalEntry[];
  trackingDaily?: DailyTrackingReport;
  trackingEvents?: MarketEvent[];
  trackingSnapshots?: MarketSnapshot[];
  jobRuns?: JobRun[];
  trackingError?: string;
  error?: string;
};

type ViewId = "overview" | "stealth" | "preopen" | "radar" | "replay" | "assistant" | "watchlist" | "stock" | "data";

type NavItem = {
  id: ViewId;
  label: string;
  description: string;
  icon: LucideIcon;
};

const analysisNav: NavItem[] = [
  { id: "replay", label: "盘后复盘", description: "错过盘面补全", icon: PlayCircle },
  { id: "overview", label: "市场总览", description: "指数、宽度、板块", icon: LayoutDashboard },
  { id: "stealth", label: "潜伏挖掘", description: "吸筹与启动候选", icon: Target },
  { id: "preopen", label: "盘前参考", description: "开盘前关注清单", icon: CalendarClock },
  { id: "radar", label: "盘中异动", description: "实时事件留痕", icon: Radio },
  { id: "assistant", label: "AI 问答", description: "只基于引用回答", icon: Bot }
];

const watchlistNav: NavItem[] = [
  { id: "watchlist", label: "自选股管理", description: "添加、分组、删除", icon: Bell },
  { id: "stock", label: "个股追踪", description: "实时档案与题材", icon: Search }
];

const systemNav: NavItem[] = [
  { id: "data", label: "数据状态", description: "来源与 Agent", icon: Database }
];

const allNav = [...analysisNav, ...watchlistNav, ...systemNav];

const importanceStyle: Record<Importance, string> = {
  critical: "border-danger/30 bg-danger/10 text-danger",
  high: "border-saffron/40 bg-saffron/10 text-[#8a5a12]",
  medium: "border-signal/25 bg-signal/10 text-signal",
  low: "border-ink/10 bg-ink/5 text-ink"
};

function viewFromHash(): ViewId {
  if (typeof window === "undefined") {
    return "replay";
  }
  const hash = window.location.hash.replace("#", "") as ViewId;
  return allNav.some((item) => item.id === hash) ? hash : "replay";
}

export function MarketLensDashboard() {
  const [state, setState] = useState<LoadState>({});
  const [activeView, setActiveView] = useState<ViewId>(() => viewFromHash());
  const [selectedSymbol, setSelectedSymbol] = useState("");
  const [query, setQuery] = useState("当前市场宽度和板块排序如何？");
  const [answer, setAnswer] = useState<AssistantAnswer | null>(null);
  const [asking, setAsking] = useState(false);
  const [selectedStealthSymbol, setSelectedStealthSymbol] = useState("");
  const [stealthDetail, setStealthDetail] = useState<StealthCandidateDetail | null>(null);
  const [stealthBusy, setStealthBusy] = useState(false);
  const [stealthError, setStealthError] = useState<string | null>(null);
  const [scanTask, setScanTask] = useState<StealthScanTask | null>(null);
  const [scanFailures, setScanFailures] = useState<StealthScanFailure[]>([]);
  const [scanMonitor, setScanMonitor] = useState<StealthScanMonitor | null>(null);
  const [scanOffset, setScanOffset] = useState(0);
  const [failureBusy, setFailureBusy] = useState(false);
  const [observationDrafts, setObservationDrafts] = useState<Record<string, { reason: string; invalidation_rule: string; next_focus: string }>>({});

  useEffect(() => {
    setActiveView(viewFromHash());
    const syncHash = () => setActiveView(viewFromHash());
    window.addEventListener("hashchange", syncHash);
    return () => window.removeEventListener("hashchange", syncHash);
  }, []);

  useEffect(() => {
    let mounted = true;

    void loadStealthCandidates({ limit: 80 })
      .then((stealthCandidates) => {
        if (!mounted) return;
        setState((current) => ({ ...current, stealthCandidates }));
        setSelectedStealthSymbol(stealthCandidates[0]?.symbol ?? "");
      })
      .catch((error: Error) => {
        if (mounted) setStealthError(error.message);
      });

    void loadStealthDiagnostics({ limit: 30, minScore: 20 })
      .then((stealthDiagnostics) => {
        if (mounted) setState((current) => ({ ...current, stealthDiagnostics }));
      })
      .catch(() => {
        if (mounted) setState((current) => ({ ...current, stealthDiagnostics: [] }));
      });

    void loadStealthObservations()
      .then((stealthObservations) => {
        if (mounted) setState((current) => ({ ...current, stealthObservations }));
      })
      .catch(() => {
        if (mounted) setState((current) => ({ ...current, stealthObservations: [] }));
      });

    void loadStealthObservationSummary()
      .then((stealthObservationSummary) => {
        if (mounted) setState((current) => ({ ...current, stealthObservationSummary }));
      })
      .catch(() => {
        if (mounted) setState((current) => ({ ...current, stealthObservationSummary: undefined }));
      });

    void loadStealthObservationJournal({ limit: 40 })
      .then((stealthObservationJournal) => {
        if (mounted) setState((current) => ({ ...current, stealthObservationJournal }));
      })
      .catch(() => {
        if (mounted) setState((current) => ({ ...current, stealthObservationJournal: [] }));
      });

    void loadLatestStealthScanTask()
      .then((task) => {
        if (mounted) setScanTask(task);
      })
      .catch(() => {
        if (mounted) setScanTask(null);
      });

    void loadStealthScanMonitor()
      .then((monitor) => {
        if (mounted) setScanMonitor(monitor);
      })
      .catch(() => {
        if (mounted) setScanMonitor(null);
      });

    void loadAgents()
      .then((agents) => {
        if (mounted) setState((current) => ({ ...current, agents }));
      })
      .catch((error: Error) => {
        if (mounted) setState((current) => ({ ...current, error: error.message }));
      });

    void Promise.all([loadTrackingDaily(), loadTrackingEvents(), loadTrackingSnapshots({ interval: "5m" }), loadAdminJobRuns({ limit: 12 })])
      .then(([trackingDaily, trackingEvents, trackingSnapshots, jobRuns]) => {
        if (mounted) setState((current) => ({ ...current, trackingDaily, trackingEvents, trackingSnapshots, jobRuns, trackingError: undefined }));
      })
      .catch((error: Error) => {
        if (mounted) {
          setState((current) => ({
            ...current,
            trackingEvents: [],
            trackingSnapshots: [],
            jobRuns: [],
            trackingError: error.message
          }));
        }
      });

    void Promise.all([loadDashboard(), loadPreopen(), loadReplay()])
      .then(([dashboard, preopen, replay]) => {
        if (mounted) setState((current) => ({ ...current, dashboard, preopen, replay, error: undefined }));
      })
      .catch((error: Error) => {
        if (mounted) setState((current) => ({ ...current, error: error.message }));
      });
    return () => {
      mounted = false;
    };
  }, []);

  useEffect(() => {
    if (!scanTask || !["queued", "running"].includes(scanTask.status)) {
      return;
    }
    const timer = window.setInterval(() => {
      void loadStealthScanTask(scanTask.id)
        .then((task) => {
          setScanTask(task);
          if (task.status === "completed") {
            void refreshStealthCandidates();
            void refreshScanMonitor();
          }
          if (task.status === "failed") {
            setStealthError(task.error || task.message || "后台扫描失败");
          }
        })
        .catch((error: Error) => setStealthError(error.message));
    }, 2500);
    return () => window.clearInterval(timer);
  }, [scanTask?.id, scanTask?.status]);

  useEffect(() => {
    if (!scanTask?.id || scanTask.failed <= 0) {
      setScanFailures([]);
      return;
    }
    void refreshScanFailures(scanTask.id);
  }, [scanTask?.id, scanTask?.failed, scanTask?.status]);

  const selectedStock = useMemo(
    () => state.dashboard?.watchlist.find((item) => item.symbol === selectedSymbol) ?? state.dashboard?.watchlist[0],
    [selectedSymbol, state.dashboard?.watchlist]
  );

  useEffect(() => {
    const observations = state.stealthObservations ?? [];
    setObservationDrafts((current) => {
      const next = { ...current };
      for (const item of observations) {
        if (!next[item.symbol]) {
          next[item.symbol] = {
            reason: item.reason ?? "",
            invalidation_rule: item.invalidation_rule ?? "",
            next_focus: item.next_focus ?? ""
          };
        }
      }
      for (const symbol of Object.keys(next)) {
        if (!observations.some((item) => item.symbol === symbol)) {
          delete next[symbol];
        }
      }
      return next;
    });
  }, [state.stealthObservations]);

  useEffect(() => {
    if (!state.dashboard) {
      return;
    }
    const exists = state.dashboard.watchlist.some((item) => item.symbol === selectedSymbol);
    if (!selectedSymbol || !exists) {
      setSelectedSymbol(state.dashboard.watchlist[0]?.symbol ?? "");
    }
  }, [selectedSymbol, state.dashboard]);

  function navigate(view: ViewId) {
    setActiveView(view);
    if (typeof window !== "undefined") {
      window.history.replaceState(null, "", `#${view}`);
    }
  }

  async function refresh() {
    setState((current) => ({ ...current, error: undefined, trackingError: undefined }));
    const [
      dashboardResult,
      preopenResult,
      replayResult,
      agentsResult,
      stealthResult,
      diagnosticsResult,
      observationsResult,
      observationSummaryResult,
      observationJournalResult,
      trackingDailyResult,
      trackingEventsResult,
      trackingSnapshotsResult,
      jobRunsResult
    ] = await Promise.allSettled([
      loadDashboard(),
      loadPreopen(),
      loadReplay(),
      loadAgents(),
      loadStealthCandidates({ limit: 80 }),
      loadStealthDiagnostics({ limit: 30, minScore: 20 }),
      loadStealthObservations(),
      loadStealthObservationSummary(),
      loadStealthObservationJournal({ limit: 40 }),
      loadTrackingDaily(),
      loadTrackingEvents(),
      loadTrackingSnapshots({ interval: "5m" }),
      loadAdminJobRuns({ limit: 12 })
    ]);
    const globalFailures = [
      dashboardResult,
      preopenResult,
      replayResult,
      agentsResult,
      stealthResult,
      diagnosticsResult,
      observationsResult,
      observationSummaryResult,
      observationJournalResult
    ]
      .filter((result): result is PromiseRejectedResult => result.status === "rejected")
      .map((result) => (result.reason instanceof Error ? result.reason.message : "鐪熷疄鏁版嵁鍔犺浇澶辫触"));
    const trackingFailures = [
      trackingDailyResult,
      trackingEventsResult,
      trackingSnapshotsResult,
      jobRunsResult
    ]
      .filter((result): result is PromiseRejectedResult => result.status === "rejected")
      .map((result) => (result.reason instanceof Error ? result.reason.message : "真实数据加载失败"));

    setState((current) => ({
      ...current,
      dashboard: dashboardResult.status === "fulfilled" ? dashboardResult.value : current.dashboard,
      preopen: preopenResult.status === "fulfilled" ? preopenResult.value : current.preopen,
      replay: replayResult.status === "fulfilled" ? replayResult.value : current.replay,
      agents: agentsResult.status === "fulfilled" ? agentsResult.value : current.agents,
      stealthCandidates: stealthResult.status === "fulfilled" ? stealthResult.value : current.stealthCandidates,
      stealthDiagnostics: diagnosticsResult.status === "fulfilled" ? diagnosticsResult.value : current.stealthDiagnostics,
      stealthObservations: observationsResult.status === "fulfilled" ? observationsResult.value : current.stealthObservations,
      stealthObservationSummary: observationSummaryResult.status === "fulfilled" ? observationSummaryResult.value : current.stealthObservationSummary,
      stealthObservationJournal: observationJournalResult.status === "fulfilled" ? observationJournalResult.value : current.stealthObservationJournal,
      trackingDaily: trackingDailyResult.status === "fulfilled" ? trackingDailyResult.value : current.trackingDaily,
      trackingEvents: trackingEventsResult.status === "fulfilled" ? trackingEventsResult.value : current.trackingEvents,
      trackingSnapshots: trackingSnapshotsResult.status === "fulfilled" ? trackingSnapshotsResult.value : current.trackingSnapshots,
      jobRuns: jobRunsResult.status === "fulfilled" ? jobRunsResult.value : current.jobRuns,
      trackingError: trackingFailures[0],
      error: globalFailures[0]
    }));
  }

  async function submitQuestion() {
    setAsking(true);
    try {
      const result = await askAssistant(query);
      setAnswer(result);
    } finally {
      setAsking(false);
    }
  }

  async function refreshStealthCandidates() {
    setStealthBusy(true);
    setStealthError(null);
    try {
      const [candidates, diagnostics, observations, observationSummary, observationJournal] = await Promise.all([
        loadStealthCandidates({ limit: 80 }),
        loadStealthDiagnostics({ limit: 30, minScore: 20 }),
        loadStealthObservations(),
        loadStealthObservationSummary(),
        loadStealthObservationJournal({ limit: 40 })
      ]);
      setState((current) => ({
        ...current,
        stealthCandidates: candidates,
        stealthDiagnostics: diagnostics,
        stealthObservations: observations,
        stealthObservationSummary: observationSummary,
        stealthObservationJournal: observationJournal
      }));
      setSelectedStealthSymbol((current) => current || candidates[0]?.symbol || "");
    } catch (error) {
      setStealthError(error instanceof Error ? error.message : "潜伏候选加载失败");
    } finally {
      setStealthBusy(false);
    }
  }

  async function refreshScanFailures(taskId = scanTask?.id) {
    if (!taskId) return;
    setFailureBusy(true);
    try {
      const failures = await loadStealthScanFailures(taskId);
      setScanFailures(failures);
    } catch (error) {
      setStealthError(error instanceof Error ? error.message : "失败明细加载失败");
    } finally {
      setFailureBusy(false);
    }
  }

  async function refreshScanMonitor() {
    try {
      const monitor = await loadStealthScanMonitor();
      setScanMonitor(monitor);
    } catch {
      setScanMonitor(null);
    }
  }

  async function refreshTrackingData() {
    const [trackingDaily, trackingEvents, trackingSnapshots, jobRuns] = await Promise.all([
      loadTrackingDaily(),
      loadTrackingEvents(),
      loadTrackingSnapshots({ interval: "5m" }),
      loadAdminJobRuns({ limit: 12 })
    ]);
    setState((current) => ({ ...current, trackingDaily, trackingEvents, trackingSnapshots, jobRuns, trackingError: undefined }));
  }

  async function runTrackingJob(jobName: string) {
    setState((current) => ({ ...current, error: undefined, trackingError: undefined }));
    try {
      const run = await runAdminJob(jobName);
      setState((current) => ({ ...current, jobRuns: [run, ...(current.jobRuns ?? [])].slice(0, 12) }));
      await refreshTrackingData();
    } catch (error) {
      const message = error instanceof Error ? error.message : "跟踪任务运行失败";
      setState((current) => ({ ...current, error: message, trackingError: message }));
    }
  }

  async function runStealthCandidateScan(offset = scanOffset) {
    setStealthBusy(true);
    setStealthError(null);
    try {
      const task = await runStealthScan({ limit: 500, offset });
      setScanTask(task);
      setScanFailures([]);
      setScanOffset(offset);
      void refreshScanMonitor();
    } catch (error) {
      setStealthError(error instanceof Error ? error.message : "扫描失败");
    } finally {
      setStealthBusy(false);
    }
  }

  async function runStealthSymbolScan(symbol: string) {
    setStealthBusy(true);
    setStealthError(null);
    try {
      const task = await runStealthScan({ symbols: [symbol] });
      setScanTask(task);
      setScanFailures([]);
      setSelectedStealthSymbol(symbol);
      void refreshScanMonitor();
    } catch (error) {
      setStealthError(error instanceof Error ? error.message : "单票补扫失败");
    } finally {
      setStealthBusy(false);
    }
  }

  async function runObservationPoolScan() {
    setStealthBusy(true);
    setStealthError(null);
    try {
      const task = await runStealthObservationScan();
      setScanTask(task);
      setScanFailures([]);
      void refreshScanMonitor();
    } catch (error) {
      setStealthError(error instanceof Error ? error.message : "观察池补扫失败");
    } finally {
      setStealthBusy(false);
    }
  }

  async function snapshotObservationJournalNow() {
    setStealthBusy(true);
    setStealthError(null);
    try {
      await snapshotStealthObservationJournal();
      const observationJournal = await loadStealthObservationJournal({ limit: 40 });
      setState((current) => ({ ...current, stealthObservationJournal: observationJournal }));
    } catch (error) {
      setStealthError(error instanceof Error ? error.message : "观察日志记录失败");
    } finally {
      setStealthBusy(false);
    }
  }

  function updateObservationDraft(symbol: string, field: "reason" | "invalidation_rule" | "next_focus", value: string) {
    setObservationDrafts((current) => ({
      ...current,
      [symbol]: {
        reason: current[symbol]?.reason ?? "",
        invalidation_rule: current[symbol]?.invalidation_rule ?? "",
        next_focus: current[symbol]?.next_focus ?? "",
        [field]: value
      }
    }));
  }

  async function saveObservationPlan(item: ObservationItem) {
    const draft = observationDrafts[item.symbol] ?? {
      reason: item.reason,
      invalidation_rule: item.invalidation_rule,
      next_focus: item.next_focus
    };
    setStealthBusy(true);
    setStealthError(null);
    try {
      await updateStealthObservation(item.symbol, {
        reason: draft.reason,
        note: item.note,
        invalidation_rule: draft.invalidation_rule,
        next_focus: draft.next_focus
      });
      const [observations, observationSummary, observationJournal] = await Promise.all([
        loadStealthObservations(),
        loadStealthObservationSummary(),
        loadStealthObservationJournal({ limit: 40 })
      ]);
      setState((current) => ({
        ...current,
        stealthObservations: observations,
        stealthObservationSummary: observationSummary,
        stealthObservationJournal: observationJournal
      }));
    } catch (error) {
      setStealthError(error instanceof Error ? error.message : "观察计划保存失败");
    } finally {
      setStealthBusy(false);
    }
  }

  async function retryFailedScanSymbols(taskId = scanTask?.id) {
    if (!taskId) return;
    setStealthBusy(true);
    setStealthError(null);
    try {
      const task = await retryStealthScanFailures(taskId);
      setScanTask(task);
      setScanFailures([]);
      void refreshScanMonitor();
    } catch (error) {
      setStealthError(error instanceof Error ? error.message : "失败股票重跑失败");
    } finally {
      setStealthBusy(false);
    }
  }

  async function resolveFailedScanSymbols(taskId = scanTask?.id) {
    if (!taskId) return;
    setFailureBusy(true);
    setStealthError(null);
    try {
      await resolveStealthScanFailures(taskId);
      await refreshScanMonitor();
      await refreshScanFailures(taskId);
    } catch (error) {
      setStealthError(error instanceof Error ? error.message : "失败项标记处理失败");
    } finally {
      setFailureBusy(false);
    }
  }

  async function selectStealthCandidate(symbol: string) {
    setSelectedStealthSymbol(symbol);
    setStealthError(null);
    try {
      const detail = await loadStealthCandidate(symbol);
      setStealthDetail(detail);
    } catch (error) {
      setStealthDetail(null);
      setStealthError(error instanceof Error ? error.message : "候选详情加载失败");
    }
  }

  async function toggleStealthObservation(candidate: StealthCandidate) {
    setStealthError(null);
    try {
      if (candidate.observed) {
        await deleteStealthObservation(candidate.symbol);
      } else {
        await observeStealthCandidate(candidate.symbol, candidate.stage);
      }
      const [candidates, diagnostics, observations, observationSummary, observationJournal] = await Promise.all([
        loadStealthCandidates({ limit: 80 }),
        loadStealthDiagnostics({ limit: 30, minScore: 20 }),
        loadStealthObservations(),
        loadStealthObservationSummary(),
        loadStealthObservationJournal({ limit: 40 })
      ]);
      setState((current) => ({
        ...current,
        stealthCandidates: candidates,
        stealthDiagnostics: diagnostics,
        stealthObservations: observations,
        stealthObservationSummary: observationSummary,
        stealthObservationJournal: observationJournal
      }));
      if (stealthDetail?.candidate.symbol === candidate.symbol) {
        const refreshed = await loadStealthCandidate(candidate.symbol);
        setStealthDetail(refreshed);
      }
    } catch (error) {
      setStealthError(error instanceof Error ? error.message : "观察状态更新失败");
    }
  }

  async function removeStealthObservation(symbol: string) {
    setStealthError(null);
    try {
      await deleteStealthObservation(symbol);
      const [candidates, diagnostics, observations, observationSummary, observationJournal] = await Promise.all([
        loadStealthCandidates({ limit: 80 }),
        loadStealthDiagnostics({ limit: 30, minScore: 20 }),
        loadStealthObservations(),
        loadStealthObservationSummary(),
        loadStealthObservationJournal({ limit: 40 })
      ]);
      setState((current) => ({
        ...current,
        stealthCandidates: candidates,
        stealthDiagnostics: diagnostics,
        stealthObservations: observations,
        stealthObservationSummary: observationSummary,
        stealthObservationJournal: observationJournal
      }));
      if (stealthDetail?.candidate.symbol === symbol) {
        const refreshed = await loadStealthCandidate(symbol);
        setStealthDetail(refreshed);
      }
    } catch (error) {
      setStealthError(error instanceof Error ? error.message : "观察项移出失败");
    }
  }

  async function addWatchlistItem(payload: { symbol: string; group: string; tags: string[] }) {
    const created = await createWatchlistItem(payload);
    setState((current) => {
      if (!current.dashboard) {
        return current;
      }
      const withoutDuplicate = current.dashboard.watchlist.filter((item) => item.symbol !== created.symbol);
      return {
        ...current,
        dashboard: {
          ...current.dashboard,
          watchlist: [created, ...withoutDuplicate]
        }
      };
    });
    setSelectedSymbol(created.symbol);
    setActiveView("stock");
    if (typeof window !== "undefined") {
      window.history.replaceState(null, "", "#stock");
    }
  }

  async function removeWatchlistItem(symbol: string) {
    await deleteWatchlistItem(symbol);
    setState((current) => {
      if (!current.dashboard) {
        return current;
      }
      return {
        ...current,
        dashboard: {
          ...current.dashboard,
          watchlist: current.dashboard.watchlist.filter((item) => item.symbol !== symbol)
        }
      };
    });
    if (selectedSymbol === symbol) {
      setSelectedSymbol("");
    }
  }

  if (activeView !== "stealth" && !state.dashboard && !state.agents && !state.error) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-paper">
        <div className="flex items-center gap-3 rounded-lg border border-ink/10 bg-white px-5 py-4 text-sm text-muted shadow-soft">
          <RefreshCcw className="animate-spin text-pine" size={18} />
          正在连接真实 A 股行情与 Agent 服务
        </div>
      </main>
    );
  }

  const { dashboard, preopen, replay, agents } = state;
  const activeItem = allNav.find((item) => item.id === activeView) ?? allNav[0];

  return (
    <main className="app-shell">
      <AppSidebar
        activeView={activeView}
        dashboard={dashboard}
        agents={agents}
        onNavigate={navigate}
        onRefresh={() => void refresh()}
      />
      <div className="ml-[112px] min-w-0 md:ml-[304px]">
        <TopBar dashboard={dashboard} marketError={state.error} onRefresh={() => void refresh()} />
        <div className="mx-auto max-w-[1320px] px-4 py-5 lg:px-6">
          <ViewHeader item={activeItem} dashboard={dashboard} />
          <div className="mt-5">
            {activeView === "overview" && (dashboard ? <OverviewView dashboard={dashboard} /> : <MarketUnavailableNotice error={state.error} onRefresh={() => void refresh()} />)}
            {activeView === "stealth" && (
              <StealthPanel
                candidates={state.stealthCandidates ?? []}
                diagnostics={state.stealthDiagnostics ?? []}
                observations={state.stealthObservations ?? []}
                observationSummary={state.stealthObservationSummary}
                observationJournal={state.stealthObservationJournal ?? []}
                observationDrafts={observationDrafts}
                selectedSymbol={selectedStealthSymbol}
                detail={stealthDetail}
                busy={stealthBusy}
                error={stealthError}
                scanTask={scanTask}
                scanFailures={scanFailures}
                scanMonitor={scanMonitor}
                scanOffset={scanOffset}
                failureBusy={failureBusy}
                onScanOffsetChange={setScanOffset}
                onRefresh={() => void refreshStealthCandidates()}
                onRunScan={() => void runStealthCandidateScan()}
                onRunNextBatch={() => void runStealthCandidateScan(scanOffset + 500)}
                onRunObservationScan={() => void runObservationPoolScan()}
                onSnapshotJournal={() => void snapshotObservationJournalNow()}
                onRunSymbolScan={(symbol) => void runStealthSymbolScan(symbol)}
                onRetryFailures={(taskId) => void retryFailedScanSymbols(taskId)}
                onResolveFailures={(taskId) => void resolveFailedScanSymbols(taskId)}
                onSelect={(symbol) => void selectStealthCandidate(symbol)}
                onToggleObserve={(candidate) => void toggleStealthObservation(candidate)}
                onRemoveObservation={(symbol) => void removeStealthObservation(symbol)}
                onObservationDraftChange={updateObservationDraft}
                onSaveObservationPlan={(item) => void saveObservationPlan(item)}
              />
            )}
            {activeView === "preopen" && (preopen ? <PreopenPanel preopen={preopen} /> : <MarketUnavailableNotice error={state.error} onRefresh={() => void refresh()} />)}
            {activeView === "radar" && (
              dashboard ? (
                <RadarPanel
                  events={state.trackingEvents?.length ? state.trackingEvents : dashboard.events}
                  snapshots={state.trackingSnapshots ?? []}
                />
              ) : (
                <MarketUnavailableNotice error={state.error} onRefresh={() => void refresh()} />
              )
            )}
            {activeView === "replay" && (
              replay ? (
                <ReplayView
                  replay={replay}
                  trackingDaily={state.trackingDaily}
                  jobRuns={state.jobRuns ?? []}
                  trackingError={state.trackingError}
                  candidates={state.stealthCandidates ?? []}
                  observationSummary={state.stealthObservationSummary}
                  agents={state.agents}
                />
              ) : (
                <MarketUnavailableNotice error={state.error} onRefresh={() => void refresh()} />
              )
            )}
            {activeView === "assistant" && (
              <AssistantPanel query={query} answer={answer} asking={asking} onQueryChange={setQuery} onSubmit={submitQuestion} />
            )}
            {activeView === "watchlist" && dashboard && (
              <WatchlistPanel
                watchlist={dashboard.watchlist}
                selectedSymbol={selectedStock?.symbol ?? ""}
                onSelect={(symbol) => {
                  setSelectedSymbol(symbol);
                  navigate("stock");
                }}
                onAdd={addWatchlistItem}
                onDelete={removeWatchlistItem}
              />
            )}
            {activeView === "watchlist" && !dashboard && <MarketUnavailableNotice error={state.error} onRefresh={() => void refresh()} />}
            {activeView === "stock" && (dashboard ? <StockFocus stock={selectedStock} sectors={dashboard.sectors} /> : <MarketUnavailableNotice error={state.error} onRefresh={() => void refresh()} />)}
            {activeView === "data" && (
              agents ? (
                <DataStatusView
                  agents={agents}
                  sources={dashboard?.sources ?? []}
                  jobRuns={state.jobRuns ?? []}
                  onRunJob={(jobName) => void runTrackingJob(jobName)}
                />
              ) : (
                <MarketUnavailableNotice error={state.error} onRefresh={() => void refresh()} />
              )
            )}
          </div>
        </div>
      </div>
    </main>
  );
}

function TopBar({ dashboard, marketError, onRefresh }: { dashboard?: DashboardResponse; marketError?: string; onRefresh: () => void }) {
  const source = dashboard?.sources[0];
  const asOf = source?.as_of ?? dashboard?.temperature.updated_at ?? new Date().toISOString();

  return (
    <header className="border-b border-ink/10 bg-paper/90 backdrop-blur">
      <div className="mx-auto flex max-w-[1500px] flex-col gap-3 px-4 py-4 lg:flex-row lg:items-center lg:justify-between lg:px-6">
        <div className="flex items-center gap-3">
          <div className="flex h-11 w-11 items-center justify-center rounded-lg bg-pine text-white">
            <Activity size={23} />
          </div>
          <div>
            <h1 className="text-xl font-semibold tracking-normal text-ink">MarketLens 盘面助手</h1>
            <p className="text-xs text-muted">
              {dashboard?.disclaimer ?? "本产品仅做公开/授权信息整理和复盘辅助，不构成证券投资建议、收益承诺、目标价或交易指令。"}
            </p>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <span className="inline-flex items-center gap-1 rounded-md border border-pine/20 bg-pine/10 px-3 py-2 text-pine">
            <ShieldCheck size={15} />
            信息整理模式
          </span>
          <span className="inline-flex items-center gap-1 rounded-md border border-signal/20 bg-signal/10 px-3 py-2 text-signal">
            <Database size={15} />
            {source?.name ?? (marketError ? "实时行情暂不可用" : "真实行情源")}
          </span>
          <span className="inline-flex items-center gap-1 rounded-md border border-ink/10 bg-white px-3 py-2 text-muted">
            <Clock3 size={15} />
            {formatDateTime(asOf)}
          </span>
          <button
            onClick={onRefresh}
            className="inline-flex min-h-9 items-center gap-1 rounded-md border border-ink/10 bg-white px-3 text-muted transition hover:border-pine/30 hover:text-pine"
            title="刷新真实行情"
          >
            <RefreshCcw size={15} />
            刷新
          </button>
        </div>
      </div>
    </header>
  );
}

function AppSidebar({
  activeView,
  dashboard,
  agents,
  onNavigate,
  onRefresh
}: {
  activeView: ViewId;
  dashboard?: DashboardResponse;
  agents?: AgentStatusResponse;
  onNavigate: (view: ViewId) => void;
  onRefresh: () => void;
}) {
  const healthyAgents = agents?.agents.filter((agent) => agent.status === "healthy").length ?? 0;

  return (
    <aside className="fixed inset-y-0 left-0 z-30 flex w-[112px] flex-col border-r border-ink/10 bg-paper/95 md:w-[304px]">
      <div className="flex h-full flex-col px-2 py-4 md:px-4 md:py-5">
        <div className="flex items-center justify-center gap-3 border-b border-ink/10 pb-4 md:justify-start md:pb-5">
          <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg bg-pine text-white">
            <Activity size={23} />
          </div>
          <div className="hidden min-w-0 md:block">
            <p className="truncate text-base font-semibold text-ink">MarketLens</p>
            <p className="text-xs text-muted">真实 A 股行情视图</p>
          </div>
        </div>

        <nav className="mt-5 space-y-5">
          <SidebarGroup title="分析部分" items={analysisNav} activeView={activeView} onNavigate={onNavigate} />
          <SidebarGroup title="自选股部分" items={watchlistNav} activeView={activeView} onNavigate={onNavigate} />
          <SidebarGroup title="系统部分" items={systemNav} activeView={activeView} onNavigate={onNavigate} />
        </nav>

        <div className="mt-5 hidden space-y-3 md:block">
          <div className="rounded-lg border border-ink/10 bg-white p-4">
            <div className="flex items-center justify-between gap-3">
              <span className="text-xs text-muted">市场温度</span>
              <span className="rounded-md bg-pine/10 px-2 py-1 text-xs font-semibold text-pine">{dashboard?.temperature.label ?? "未连接"}</span>
            </div>
            <p className="mt-2 text-4xl font-semibold text-ink">{dashboard?.temperature.score ?? "--"}</p>
            <p className="mt-1 text-xs text-muted">
              上涨 {dashboard?.temperature.advancers ?? "--"} / 下跌 {dashboard?.temperature.decliners ?? "--"}
            </p>
          </div>

          <div className="grid grid-cols-2 gap-2">
            <SidebarMetric label="自选" value={dashboard?.watchlist.length.toString() ?? "--"} />
            <SidebarMetric label="事件" value={dashboard?.events.length.toString() ?? "--"} />
            <SidebarMetric label="数据源" value={dashboard?.sources.length.toString() ?? "--"} />
            <SidebarMetric label="Agent" value={agents ? `${healthyAgents}/${agents.agents.length}` : "--"} />
          </div>
        </div>

        <div className="mt-auto space-y-3 border-t border-ink/10 pt-4">
          <div className="hidden items-start gap-2 rounded-lg border border-pine/20 bg-pine/10 p-3 text-xs leading-5 text-pine md:flex">
            <ShieldCheck className="mt-0.5 shrink-0" size={15} />
            <span>无本地假行情兜底；真实源不可用时页面会直接提示。</span>
          </div>
          <button
            onClick={onRefresh}
            className="flex min-h-10 w-full items-center justify-center gap-2 rounded-md bg-ink px-3 text-sm font-semibold text-white transition hover:bg-pine"
          >
            <RefreshCcw size={16} />
            <span className="hidden md:inline">刷新实时数据</span>
          </button>
        </div>
      </div>
    </aside>
  );
}

function SidebarGroup({
  title,
  items,
  activeView,
  onNavigate
}: {
  title: string;
  items: NavItem[];
  activeView: ViewId;
  onNavigate: (view: ViewId) => void;
}) {
  return (
    <div>
      <p className="px-1 text-center text-[11px] font-semibold text-muted md:px-2 md:text-left md:text-xs">{title}</p>
      <div className="mt-2 space-y-1">
        {items.map((item) => {
          const Icon = item.icon;
          const active = activeView === item.id;
          return (
            <button
              key={item.id}
              onClick={() => onNavigate(item.id)}
              className={`flex min-h-12 w-full flex-col items-center justify-center gap-1 rounded-md px-1 text-center transition md:flex-row md:justify-start md:gap-3 md:px-3 md:text-left ${
                active ? "bg-pine text-white shadow-soft" : "text-muted hover:bg-pine/10 hover:text-pine"
              }`}
            >
              <Icon size={18} />
              <span className="min-w-0">
                <span className="block text-[11px] font-semibold leading-4 md:text-sm">{item.label}</span>
                <span className={`hidden truncate text-xs md:block ${active ? "text-white/75" : "text-muted"}`}>{item.description}</span>
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}

function SidebarMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-ink/10 bg-white p-3">
      <p className="text-xs text-muted">{label}</p>
      <p className="mt-1 text-lg font-semibold text-ink">{value}</p>
    </div>
  );
}

function MobileNav({ activeView, onNavigate }: { activeView: ViewId; onNavigate: (view: ViewId) => void }) {
  return (
    <div className="sticky top-0 z-20 border-b border-ink/10 bg-paper/95 backdrop-blur md:hidden">
      <nav className="no-scrollbar flex gap-2 overflow-x-auto px-4 py-3">
        {allNav.map((item) => {
          const Icon = item.icon;
          const active = activeView === item.id;
          return (
            <button
              key={item.id}
              onClick={() => onNavigate(item.id)}
              className={`inline-flex min-h-10 shrink-0 items-center gap-2 rounded-md border px-3 text-sm font-medium ${
                active ? "border-pine bg-pine text-white" : "border-ink/10 bg-white text-muted"
              }`}
            >
              <Icon size={16} />
              {item.label}
            </button>
          );
        })}
      </nav>
    </div>
  );
}

function ViewHeader({ item, dashboard }: { item: NavItem; dashboard?: DashboardResponse }) {
  const Icon = item.icon;
  return (
    <section className="flex flex-col justify-between gap-4 rounded-lg border border-ink/10 bg-white px-5 py-4 md:flex-row md:items-center">
      <div className="flex items-center gap-3">
        <span className="flex h-10 w-10 items-center justify-center rounded-md bg-pine/10 text-pine">
          <Icon size={20} />
        </span>
        <div>
          <h2 className="text-xl font-semibold text-ink">{item.label}</h2>
          <p className="text-sm text-muted">{item.description}</p>
        </div>
      </div>
      <div className="flex flex-wrap gap-2 text-xs">
        <span className="rounded-md border border-ink/10 bg-paper px-2.5 py-1 text-muted">
          {dashboard ? `更新 ${formatDateTime(dashboard.temperature.updated_at)}` : "行情未连接"}
        </span>
        <span className="rounded-md border border-pine/20 bg-pine/10 px-2.5 py-1 text-pine">实时源 {dashboard?.sources.length ?? "--"}</span>
      </div>
    </section>
  );
}

function MarketUnavailableNotice({ error, onRefresh }: { error?: string; onRefresh: () => void }) {
  return (
    <section className="rounded-lg border border-danger/20 bg-white p-5">
      <div className="flex items-center gap-3 text-danger">
        <AlertTriangle size={20} />
        <h3 className="text-base font-semibold">真实行情暂不可用</h3>
      </div>
      <p className="mt-3 text-sm leading-6 text-muted">
        页面不会使用本地假行情兜底；外部行情源恢复后可刷新重新连接。潜伏挖掘、观察列表等数据库模块仍可使用。
      </p>
      {error && <p className="mt-3 rounded-md border border-danger/15 bg-danger/5 px-3 py-2 text-xs leading-5 text-danger">{error}</p>}
      <button
        onClick={onRefresh}
        className="mt-4 inline-flex min-h-10 items-center gap-2 rounded-md bg-ink px-4 text-sm font-semibold text-white transition hover:bg-pine"
      >
        <RefreshCcw size={16} />
        重新连接
      </button>
    </section>
  );
}

function OverviewView({ dashboard }: { dashboard: DashboardResponse }) {
  return (
    <div className="grid grid-cols-1 gap-5 xl:grid-cols-[1.05fr_0.95fr]">
      <MarketPulse dashboard={dashboard} />
      <div className="space-y-5">
        <SectorBoard sectors={dashboard.sectors} />
        <RadarSummary events={dashboard.events} />
      </div>
    </div>
  );
}

function MarketPulse({ dashboard }: { dashboard: DashboardResponse }) {
  const sectorData = dashboard.sectors.map((sector) => ({ name: sector.name, change: sector.change_pct }));

  return (
    <section className="panel rounded-lg p-5">
      <div className="flex flex-col justify-between gap-4 md:flex-row md:items-start">
        <div>
          <p className="text-xs font-semibold uppercase text-pine">今日市场温度</p>
          <div className="mt-2 flex items-end gap-4">
            <span className="text-6xl font-semibold text-ink">{dashboard.temperature.score}</span>
            <div className="pb-2">
              <p className="text-xl font-semibold text-pine">{dashboard.temperature.label}</p>
              <p className="text-sm text-muted">
                上涨 {dashboard.temperature.advancers} / 下跌 {dashboard.temperature.decliners}
              </p>
            </div>
          </div>
        </div>
        <div className="grid grid-cols-2 gap-2 text-sm sm:grid-cols-4">
          <Metric label="涨停" value={dashboard.temperature.limit_up_count.toString()} tone="up" />
          <Metric label="跌停" value={dashboard.temperature.limit_down_count.toString()} tone="down" />
          <Metric label="成交额" value={`${dashboard.temperature.total_turnover_billion.toFixed(0)}亿`} />
          <Metric label="事件" value={dashboard.events.length.toString()} />
        </div>
      </div>

      <div className="mt-6 grid grid-cols-1 gap-4 lg:grid-cols-[1fr_300px]">
        <div className="h-64 rounded-lg border border-ink/10 bg-white p-3">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={sectorData}>
              <CartesianGrid stroke="#e4e0d7" strokeDasharray="3 3" />
              <XAxis dataKey="name" tick={{ fontSize: 12 }} />
              <YAxis tick={{ fontSize: 12 }} />
              <Tooltip />
              <Bar dataKey="change" fill="#285f9f" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
        <div className="space-y-3">
          {dashboard.indexes.map((index) => (
            <div key={index.symbol} className="rounded-lg border border-ink/10 bg-white p-4">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <p className="text-sm font-semibold">{index.name}</p>
                  <p className="text-xs text-muted">{index.symbol}</p>
                </div>
                <Change value={index.change_pct} />
              </div>
              <p className="mt-3 text-2xl font-semibold">{index.value.toFixed(2)}</p>
              <p className="text-xs text-muted">成交额 {index.turnover_billion.toFixed(0)} 亿</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

function SectorBoard({ sectors }: { sectors: SectorSnapshot[] }) {
  return (
    <section className="panel rounded-lg p-5">
      <SectionTitle icon={LineChart} title="实时排行/板块" aside={`${sectors.length} 组`} />
      <div className="mt-4 space-y-3">
        {sectors.map((sector) => (
          <article key={sector.name} className="rounded-lg border border-ink/10 bg-white p-4">
            <div className="flex items-start justify-between gap-3">
              <div>
                <h3 className="text-sm font-semibold">{sector.name}</h3>
                <p className="mt-1 text-xs text-muted">成交额 {sector.turnover_billion.toFixed(0)} 亿</p>
              </div>
              <Change value={sector.change_pct} />
            </div>
            <p className="mt-3 text-sm leading-6 text-muted">{sector.driver}</p>
          </article>
        ))}
      </div>
    </section>
  );
}

function RadarSummary({ events }: { events: MarketEvent[] }) {
  return (
    <section className="panel rounded-lg p-5">
      <SectionTitle icon={Radio} title="事件摘要" aside={`${events.length} 条`} />
      <div className="mt-4 space-y-3">
        {events.slice(0, 4).map((event) => (
          <article key={event.id} className="rounded-lg border border-ink/10 bg-white p-4">
            <div className="flex flex-wrap items-center gap-2">
              <Pill importance={event.importance} />
              <time className="text-xs text-muted">{formatTime(event.occurred_at)}</time>
            </div>
            <h3 className="mt-3 text-sm font-semibold">{event.title}</h3>
            <p className="mt-2 text-sm leading-6 text-muted">{event.summary}</p>
          </article>
        ))}
      </div>
    </section>
  );
}

function StealthPanel({
  candidates,
  diagnostics,
  observations,
  observationSummary,
  observationJournal,
  observationDrafts,
  selectedSymbol,
  detail,
  busy,
  error,
  scanTask,
  scanFailures,
  scanMonitor,
  scanOffset,
  failureBusy,
  onScanOffsetChange,
  onRefresh,
  onRunScan,
  onRunNextBatch,
  onRunObservationScan,
  onSnapshotJournal,
  onRunSymbolScan,
  onRetryFailures,
  onResolveFailures,
  onSelect,
  onToggleObserve,
  onRemoveObservation,
  onObservationDraftChange,
  onSaveObservationPlan
}: {
  candidates: StealthCandidate[];
  diagnostics: StealthCandidate[];
  observations: ObservationItem[];
  observationSummary?: ObservationSummary;
  observationJournal: ObservationJournalEntry[];
  observationDrafts: Record<string, { reason: string; invalidation_rule: string; next_focus: string }>;
  selectedSymbol: string;
  detail: StealthCandidateDetail | null;
  busy: boolean;
  error: string | null;
  scanTask: StealthScanTask | null;
  scanFailures: StealthScanFailure[];
  scanMonitor: StealthScanMonitor | null;
  scanOffset: number;
  failureBusy: boolean;
  onScanOffsetChange: (offset: number) => void;
  onRefresh: () => void;
  onRunScan: () => void;
  onRunNextBatch: () => void;
  onRunObservationScan: () => void;
  onSnapshotJournal: () => void;
  onRunSymbolScan: (symbol: string) => void;
  onRetryFailures: (taskId?: string) => void;
  onResolveFailures: (taskId?: string) => void;
  onSelect: (symbol: string) => void;
  onToggleObserve: (candidate: StealthCandidate) => void;
  onRemoveObservation: (symbol: string) => void;
  onObservationDraftChange: (symbol: string, field: "reason" | "invalidation_rule" | "next_focus", value: string) => void;
  onSaveObservationPlan: (item: ObservationItem) => void;
}) {
  const activeCandidate = detail?.candidate ?? candidates.find((item) => item.symbol === selectedSymbol) ?? candidates[0];
  const stageCounts = candidates.reduce<Record<string, number>>((acc, item) => {
    acc[item.stage] = (acc[item.stage] ?? 0) + 1;
    return acc;
  }, {});
  const chartData = (detail?.bars ?? [])
    .slice(-80)
    .map((bar) => ({ date: bar.trade_date.slice(5), close: bar.close, amount: Math.round(bar.amount / 100000000) }));
  const scanRunning = scanTask?.status === "queued" || scanTask?.status === "running";
  const scanProgress = scanTask?.total ? Math.min(100, Math.round(((scanTask.scanned + scanTask.failed) / scanTask.total) * 100)) : 0;
  const unresolvedFailures = scanFailures.filter((failure) => !failure.resolved);
  const visibleFailures = scanFailures.slice(0, 6);
  const visibleDiagnostics = diagnostics.slice(0, 6);
  const quality = scanMonitor?.data_quality;
  const latestFailureRate = `${Math.round((scanMonitor?.latest_failure_rate ?? 0) * 100)}%`;
  const recoverableFailureTask = scanMonitor?.latest_tasks.find((task) => task.failed > 0);
  const summaryBuckets = observationSummary?.buckets.filter((bucket) => bucket.count > 0) ?? [];
  const summaryUpdatedAt = observationSummary?.updated_at ? formatTime(observationSummary.updated_at) : "--";
  const latestJournal = observationJournal.slice(0, 8);

  return (
    <section className="panel rounded-lg p-5">
      <div className="flex flex-col justify-between gap-4 xl:flex-row xl:items-start">
        <SectionTitle icon={Target} title="潜伏挖掘" aside={`${candidates.length} 个候选`} />
        <div className="flex flex-wrap gap-2">
          <button
            onClick={onRefresh}
            disabled={busy}
            className="inline-flex min-h-10 items-center gap-2 rounded-md border border-ink/10 bg-white px-3 text-sm font-semibold text-muted transition hover:border-pine/30 hover:text-pine disabled:opacity-60"
          >
            <RefreshCcw className={busy ? "animate-spin" : ""} size={16} />
            刷新候选
          </button>
          <button
            onClick={onRunScan}
            disabled={busy || scanRunning}
            className="inline-flex min-h-10 items-center gap-2 rounded-md bg-pine px-3 text-sm font-semibold text-white transition hover:bg-[#0b514a] disabled:opacity-60"
          >
            <Target className={scanRunning ? "animate-pulse" : ""} size={16} />
            {scanRunning ? "扫描中" : "运行批次"}
          </button>
          <button
            onClick={onRunNextBatch}
            disabled={busy || scanRunning}
            className="inline-flex min-h-10 items-center gap-2 rounded-md border border-ink/10 bg-white px-3 text-sm font-semibold text-muted transition hover:border-pine/30 hover:text-pine disabled:opacity-60"
          >
            <PlayCircle size={16} />
            下一批
          </button>
          <button
            onClick={onRunObservationScan}
            disabled={busy || scanRunning || observations.length === 0}
            className="inline-flex min-h-10 items-center gap-2 rounded-md border border-pine/25 bg-pine/5 px-3 text-sm font-semibold text-pine transition hover:border-pine/40 hover:bg-pine/10 disabled:opacity-60"
          >
            <Bell size={16} />
            补扫观察池
          </button>
          <label className="inline-flex min-h-10 items-center gap-2 rounded-md border border-ink/10 bg-white px-3 text-xs font-semibold text-muted">
            offset
            <input
              type="number"
              min={0}
              step={500}
              value={scanOffset}
              onChange={(event) => onScanOffsetChange(Math.max(0, Number(event.target.value) || 0))}
              className="w-24 bg-transparent text-sm text-ink outline-none"
            />
          </label>
        </div>
      </div>

      <div className="mt-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StealthMetric label="潜伏观察" value={(stageCounts["潜伏观察"] ?? 0).toString()} />
        <StealthMetric label="启动确认" value={(stageCounts["启动确认"] ?? 0).toString()} tone="signal" />
        <StealthMetric label="过热排除" value={(stageCounts["过热排除"] ?? 0).toString()} tone="danger" />
        <StealthMetric label="扫描保存" value={scanTask ? `${scanTask.saved}/${scanTask.scanned}` : "--"} />
      </div>

      {scanMonitor && (
        <div className="mt-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
          <StealthMetric label="最近失败率" value={latestFailureRate} tone={(scanMonitor.latest_failure_rate ?? 0) >= 0.2 ? "danger" : undefined} />
          <StealthMetric label="未恢复失败" value={scanMonitor.unresolved_failures.toString()} tone={scanMonitor.unresolved_failures ? "danger" : undefined} />
          <StealthMetric label="平均耗时" value={`${Math.round(scanMonitor.avg_duration_seconds)}s`} />
          <StealthMetric label="最新日线" value={quality?.latest_trade_date ?? "--"} />
        </div>
      )}

      {quality && (
        <div className="mt-4 rounded-md border border-ink/10 bg-white px-3 py-3 text-xs leading-6 text-muted">
          数据质量：股票池 {quality.universe_symbols} / 有日线 {quality.symbols_with_bars} / 最新日线覆盖 {quality.latest_bar_symbols} / 滞后 {quality.stale_symbols} / 零成交额 {quality.zero_amount_symbols} / 历史不足 {quality.short_history_symbols}
        </div>
      )}

      {scanMonitor?.alerts.length ? (
        <div className="mt-4 grid gap-2">
          {scanMonitor.alerts.slice(0, 4).map((alert) => (
            <div
              key={`${alert.metric}-${alert.message}`}
              className={`rounded-md border px-3 py-2 text-sm leading-6 ${
                alert.level === "critical"
                  ? "border-danger/20 bg-danger/5 text-danger"
                  : alert.level === "warning"
                    ? "border-amber-200 bg-amber-50 text-amber-800"
                    : "border-ink/10 bg-white text-muted"
              }`}
            >
              {alert.message}
            </div>
          ))}
        </div>
      ) : null}

      {scanMonitor && scanMonitor.unresolved_failures > 0 && recoverableFailureTask && (
        <div className="mt-4 flex flex-wrap items-center justify-between gap-3 rounded-md border border-amber-200 bg-amber-50 px-3 py-3 text-sm leading-6 text-amber-900">
          <span>
            仍有 {scanMonitor.unresolved_failures} 个历史失败项，最近可处理任务 {recoverableFailureTask.id.slice(0, 8)}。
          </span>
          <div className="flex flex-wrap gap-2">
            <button
              onClick={() => onRetryFailures(recoverableFailureTask.id)}
              disabled={busy || scanRunning}
              className="inline-flex min-h-8 items-center gap-2 rounded-md border border-amber-300 bg-white px-2.5 text-xs font-semibold text-amber-900 transition hover:border-pine/30 hover:text-pine disabled:opacity-50"
            >
              <RefreshCcw size={14} />
              重跑当前失败项
            </button>
            <button
              onClick={() => onResolveFailures(recoverableFailureTask.id)}
              disabled={failureBusy}
              className="inline-flex min-h-8 items-center gap-2 rounded-md border border-amber-300 bg-white px-2.5 text-xs font-semibold text-amber-900 transition hover:border-pine/30 hover:text-pine disabled:opacity-50"
            >
              <CheckCircle2 size={14} />
              标记已处理
            </button>
          </div>
        </div>
      )}

      {visibleDiagnostics.length > 0 && (
        <div className="mt-4 rounded-md border border-ink/10 bg-white p-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="inline-flex items-center gap-2 text-sm font-semibold text-ink">
              <LineChart size={16} className="text-pine" />
              策略诊断观察池
            </div>
            <span className="text-xs text-muted">未入选但接近阈值</span>
          </div>
          <div className="mt-3 grid gap-2 lg:grid-cols-2">
            {visibleDiagnostics.map((item) => (
              <button
                key={item.symbol}
                onClick={() => onSelect(item.symbol)}
                className="rounded-md border border-ink/10 bg-paper px-3 py-2 text-left text-xs leading-5 transition hover:border-pine/30 hover:bg-pine/5"
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="font-semibold text-ink">
                    {item.symbol} {item.name}
                  </span>
                  <span className="text-pine">总分 {item.total_score.toFixed(0)}</span>
                </div>
                <p className="mt-1 text-muted">
                  潜伏 {item.accumulation_score.toFixed(0)} / 启动 {item.launch_score.toFixed(0)} / 题材 {item.theme_score.toFixed(0)}
                </p>
                <p className="mt-1 text-danger">{item.risks[0] ?? "未达到观察阈值，继续跟踪结构变化。"}</p>
              </button>
            ))}
          </div>
        </div>
      )}

      {observationSummary && (
        <div className="mt-4 rounded-md border border-ink/10 bg-white p-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="inline-flex items-center gap-2 text-sm font-semibold text-ink">
              <ShieldCheck size={16} className="text-pine" />
              今日观察摘要
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-xs text-muted">更新 {summaryUpdatedAt}</span>
              <button
                onClick={onRunObservationScan}
                disabled={busy || scanRunning || observationSummary.total === 0}
                className="inline-flex min-h-8 items-center gap-1.5 rounded-md border border-pine/25 bg-pine/5 px-2.5 text-xs font-semibold text-pine transition hover:border-pine/40 hover:bg-pine/10 disabled:opacity-50"
              >
                <RefreshCcw size={14} />
                一键补扫
              </button>
            </div>
          </div>
          <div className="mt-3 grid grid-cols-2 gap-2 lg:grid-cols-5">
            <div className="rounded-md bg-paper px-3 py-2">
              <p className="text-[11px] text-muted">总观察</p>
              <p className="mt-1 text-lg font-semibold text-ink">{observationSummary.total}</p>
            </div>
            <div className="rounded-md bg-pine/5 px-3 py-2">
              <p className="text-[11px] text-muted">继续观察</p>
              <p className="mt-1 text-lg font-semibold text-pine">{observationSummary.continue_count}</p>
            </div>
            <div className="rounded-md bg-signal/10 px-3 py-2">
              <p className="text-[11px] text-muted">启动确认</p>
              <p className="mt-1 text-lg font-semibold text-signal">{observationSummary.activation_count}</p>
            </div>
            <div className="rounded-md bg-danger/5 px-3 py-2">
              <p className="text-[11px] text-muted">失效检查</p>
              <p className="mt-1 text-lg font-semibold text-danger">{observationSummary.invalid_count}</p>
            </div>
            <div className="rounded-md bg-amber-50 px-3 py-2">
              <p className="text-[11px] text-muted">待补扫</p>
              <p className="mt-1 text-lg font-semibold text-amber-800">{observationSummary.data_gap_count}</p>
            </div>
          </div>
          {summaryBuckets.length > 0 ? (
            <div className="mt-3 grid gap-2 xl:grid-cols-2">
              {summaryBuckets.map((bucket) => (
                <div key={bucket.key} className="rounded-md border border-ink/10 bg-paper px-3 py-2 text-xs leading-5">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="font-semibold text-ink">{bucket.label}</span>
                    <span className="text-muted">{bucket.count} 个</span>
                  </div>
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {bucket.items.slice(0, 5).map((item) => (
                      <button
                        key={`${bucket.key}-${item.symbol}`}
                        onClick={() => onSelect(item.symbol)}
                        className="rounded-md border border-ink/10 bg-white px-2 py-1 text-[11px] font-semibold text-muted transition hover:border-pine/30 hover:text-pine"
                      >
                        {item.symbol}
                        {item.candidate ? ` ${item.candidate.total_score.toFixed(0)}` : ""}
                      </button>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <p className="mt-3 text-xs leading-5 text-muted">观察池还没有标的。先从候选表加入观察，再用补扫维持每日状态。</p>
          )}
        </div>
      )}

      <div className="mt-4 rounded-md border border-ink/10 bg-white p-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="inline-flex items-center gap-2 text-sm font-semibold text-ink">
            <FileText size={16} className="text-pine" />
            观察日志
          </div>
          <button
            onClick={onSnapshotJournal}
            disabled={busy || observations.length === 0}
            className="inline-flex min-h-8 items-center gap-1.5 rounded-md border border-ink/10 bg-white px-2.5 text-xs font-semibold text-muted transition hover:border-pine/30 hover:text-pine disabled:opacity-50"
          >
            <CheckCircle2 size={14} />
            记录今日
          </button>
        </div>
        {latestJournal.length > 0 ? (
          <div className="mt-3 grid gap-2 xl:grid-cols-2">
            {latestJournal.map((entry) => (
              <button
                key={`${entry.symbol}-${entry.trading_day}-${entry.updated_at}`}
                onClick={() => onSelect(entry.symbol)}
                className="rounded-md border border-ink/10 bg-paper px-3 py-2 text-left text-xs leading-5 transition hover:border-pine/30 hover:bg-pine/5"
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="font-semibold text-ink">
                    {entry.symbol} {entry.name}
                  </span>
                  <span className="text-muted">{formatTradeDate(entry.trading_day)}</span>
                </div>
                <div className="mt-1 flex flex-wrap items-center gap-2">
                  <span className={`rounded-md border px-2 py-1 text-[11px] font-semibold ${journalBucketTone(entry.bucket_key)}`}>
                    {entry.bucket_label}
                  </span>
                  <span className="text-muted">{entry.transition_label}</span>
                  {typeof entry.total_score === "number" && <span className="font-semibold text-pine">总分 {entry.total_score.toFixed(0)}</span>}
                </div>
                <p className="mt-1 line-clamp-2 text-muted">{entry.decision_summary}</p>
                {(entry.observation_reason || entry.manual_invalidation_rule || entry.next_focus) && (
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {entry.observation_reason && <span className="rounded-md bg-white px-2 py-1 text-[11px] text-muted">理由 {entry.observation_reason}</span>}
                    {entry.manual_invalidation_rule && <span className="rounded-md bg-white px-2 py-1 text-[11px] text-danger">失效 {entry.manual_invalidation_rule}</span>}
                    {entry.next_focus && <span className="rounded-md bg-white px-2 py-1 text-[11px] text-pine">重点 {entry.next_focus}</span>}
                  </div>
                )}
              </button>
            ))}
          </div>
        ) : (
          <p className="mt-3 text-xs leading-5 text-muted">还没有观察日志。点击“记录今日”，或完成观察池补扫后会自动写入。</p>
        )}
      </div>

      {observations.length > 0 && (
        <div className="mt-4 rounded-md border border-pine/15 bg-pine/5 p-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="inline-flex items-center gap-2 text-sm font-semibold text-ink">
              <Bell size={16} className="text-pine" />
              每日观察池
            </div>
            <span className="text-xs text-muted">{observations.length} 个跟踪标的</span>
          </div>
          <div className="mt-3 grid gap-2 xl:grid-cols-2">
            {observations.slice(0, 8).map((item) => {
              const candidate = item.candidate;
              const draft = observationDrafts[item.symbol] ?? {
                reason: item.reason ?? "",
                invalidation_rule: item.invalidation_rule ?? "",
                next_focus: item.next_focus ?? ""
              };
              return (
                <div key={item.symbol} className="rounded-md border border-ink/10 bg-white px-3 py-2 text-xs leading-5">
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <button onClick={() => onSelect(item.symbol)} className="text-left">
                      <span className="font-semibold text-ink">
                        {item.symbol} {candidate?.name ?? ""}
                      </span>
                      <span className="ml-2 text-muted">观察 {item.days_observed} 天</span>
                    </button>
                    <div className="flex gap-1.5">
                      <button
                        onClick={() => onRunSymbolScan(item.symbol)}
                        disabled={busy || scanRunning}
                        className="rounded-md border border-ink/10 px-2 py-1 text-[11px] font-semibold text-muted transition hover:border-pine/30 hover:text-pine disabled:opacity-50"
                      >
                        补扫
                      </button>
                      <button
                        onClick={() => onRemoveObservation(item.symbol)}
                        className="rounded-md border border-ink/10 px-2 py-1 text-[11px] font-semibold text-muted transition hover:border-danger/30 hover:text-danger"
                      >
                        移出
                      </button>
                    </div>
                  </div>
                  <div className="mt-1 flex flex-wrap items-center gap-2">
                    {candidate ? <StageBadge stage={candidate.stage} /> : <span className="rounded-md border border-ink/10 bg-paper px-2 py-1 text-[11px] text-muted">待补扫</span>}
                    {candidate && <span className="font-semibold text-pine">总分 {candidate.total_score.toFixed(0)}</span>}
                    {item.reason && <span className="text-muted">理由：{item.reason}</span>}
                  </div>
                  <p className="mt-1 text-muted">
                    {candidate
                      ? `潜伏 ${candidate.accumulation_score.toFixed(0)} / 启动 ${candidate.launch_score.toFixed(0)} / 题材 ${candidate.theme_score.toFixed(0)}`
                      : "最新扫描结果里没有该股票，建议单票补扫。"}
                  </p>
                  {item.invalidation_reasons[0] && <p className="mt-1 text-danger">失效观察：{item.invalidation_reasons[0]}</p>}
                  <div className="mt-3 rounded-md border border-ink/10 bg-paper/70 p-2">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <span className="font-semibold text-ink">人工观察计划</span>
                      <button
                        onClick={() => onSaveObservationPlan(item)}
                        disabled={busy}
                        className="rounded-md border border-pine/25 bg-white px-2 py-1 text-[11px] font-semibold text-pine transition hover:bg-pine/5 disabled:opacity-50"
                      >
                        保存
                      </button>
                    </div>
                    <div className="mt-2 grid gap-2 lg:grid-cols-3">
                      <label className="grid gap-1">
                        <span className="text-[11px] font-semibold text-muted">观察理由</span>
                        <textarea
                          value={draft.reason}
                          maxLength={300}
                          rows={2}
                          onChange={(event) => onObservationDraftChange(item.symbol, "reason", event.target.value)}
                          className="min-h-[54px] resize-none rounded-md border border-ink/10 bg-white px-2 py-1.5 text-xs leading-5 text-ink outline-none transition focus:border-pine/40"
                        />
                      </label>
                      <label className="grid gap-1">
                        <span className="text-[11px] font-semibold text-muted">失效条件</span>
                        <textarea
                          value={draft.invalidation_rule}
                          maxLength={500}
                          rows={2}
                          onChange={(event) => onObservationDraftChange(item.symbol, "invalidation_rule", event.target.value)}
                          className="min-h-[54px] resize-none rounded-md border border-ink/10 bg-white px-2 py-1.5 text-xs leading-5 text-ink outline-none transition focus:border-pine/40"
                        />
                      </label>
                      <label className="grid gap-1">
                        <span className="text-[11px] font-semibold text-muted">下次重点</span>
                        <textarea
                          value={draft.next_focus}
                          maxLength={500}
                          rows={2}
                          onChange={(event) => onObservationDraftChange(item.symbol, "next_focus", event.target.value)}
                          className="min-h-[54px] resize-none rounded-md border border-ink/10 bg-white px-2 py-1.5 text-xs leading-5 text-ink outline-none transition focus:border-pine/40"
                        />
                      </label>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {error && <p className="mt-4 rounded-md border border-danger/20 bg-danger/5 px-3 py-2 text-sm leading-6 text-danger">{error}</p>}
      {scanTask && (
        <div className="mt-4 rounded-md border border-pine/20 bg-pine/10 px-3 py-3 text-sm leading-6 text-pine">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span>{scanTask.message || "后台扫描任务已创建。"}</span>
            <span className="font-semibold">
              {scanTask.status === "completed" ? "已完成" : scanTask.status === "failed" ? "失败" : `${scanProgress}%`}
            </span>
          </div>
          <div className="mt-2 h-2 overflow-hidden rounded-full bg-white/80">
            <div className="h-full rounded-full bg-pine transition-all" style={{ width: `${scanTask.status === "completed" ? 100 : scanProgress}%` }} />
          </div>
          <p className="mt-2 text-xs text-pine/80">
            总数 {scanTask.total || "--"} / 已扫 {scanTask.scanned} / 失败 {scanTask.failed} / 保存 {scanTask.saved}
            {scanTask.error ? `；${scanTask.error}` : ""}
          </p>
          {scanTask.failed > 0 && (
            <div className="mt-3 rounded-md border border-pine/15 bg-white/75 p-3 text-ink">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="inline-flex items-center gap-2 text-sm font-semibold">
                  <AlertTriangle size={16} className="text-danger" />
                  失败明细 {failureBusy ? "加载中" : `${scanFailures.length || scanTask.failed} 条`}
                </div>
                <button
                  onClick={() => onRetryFailures()}
                  disabled={busy || scanRunning || unresolvedFailures.length === 0}
                  className="inline-flex min-h-8 items-center gap-2 rounded-md border border-ink/10 bg-white px-2.5 text-xs font-semibold text-muted transition hover:border-pine/30 hover:text-pine disabled:opacity-50"
                >
                  <RefreshCcw size={14} />
                  重跑失败项
                </button>
                <button
                  onClick={() => onResolveFailures()}
                  disabled={failureBusy || unresolvedFailures.length === 0}
                  className="inline-flex min-h-8 items-center gap-2 rounded-md border border-ink/10 bg-white px-2.5 text-xs font-semibold text-muted transition hover:border-pine/30 hover:text-pine disabled:opacity-50"
                >
                  <CheckCircle2 size={14} />
                  标记已处理
                </button>
              </div>
              {visibleFailures.length > 0 ? (
                <div className="mt-2 grid gap-2">
                  {visibleFailures.map((failure) => (
                    <div key={failure.id} className="rounded-md border border-ink/10 bg-white px-2.5 py-2 text-xs leading-5">
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <span className="font-semibold text-ink">
                          {failure.symbol} {failure.name}
                        </span>
                        <span className={failure.resolved ? "text-pine" : "text-danger"}>
                          {failure.resolved ? "已恢复" : `${failure.stage} 失败`}
                          {failure.retry_count ? ` / 重试 ${failure.retry_count}` : ""}
                        </span>
                      </div>
                      <p className="mt-1 break-words text-muted">{failure.error}</p>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="mt-2 text-xs text-muted">暂无失败明细，新的扫描任务会自动记录具体标的和失败原因。</p>
              )}
            </div>
          )}
        </div>
      )}

      <div className="mt-5 grid grid-cols-1 gap-5 xl:grid-cols-[1.05fr_0.95fr]">
        <div className="overflow-x-auto rounded-lg border border-ink/10 bg-white">
          <table className="dense-table min-w-[900px]">
            <thead>
              <tr>
                <th>候选</th>
                <th>阶段</th>
                <th>总分</th>
                <th>潜伏</th>
                <th>启动</th>
                <th>题材</th>
                <th>风险</th>
                <th>证据摘要</th>
                <th>观察</th>
              </tr>
            </thead>
            <tbody>
              {candidates.map((candidate) => (
                <tr
                  key={candidate.symbol}
                  className={`transition hover:bg-pine/5 ${activeCandidate?.symbol === candidate.symbol ? "bg-pine/10" : ""}`}
                  onClick={() => onSelect(candidate.symbol)}
                >
                  <td>
                    <button className="text-left" title={`查看 ${candidate.name}`}>
                      <span className="block font-semibold">{candidate.name}</span>
                      <span className="text-xs text-muted">{candidate.symbol}</span>
                    </button>
                  </td>
                  <td>
                    <StageBadge stage={candidate.stage} />
                  </td>
                  <td>
                    <ScoreBadge value={candidate.total_score} />
                  </td>
                  <td>{candidate.accumulation_score.toFixed(0)}</td>
                  <td>{candidate.launch_score.toFixed(0)}</td>
                  <td>{candidate.theme_score.toFixed(0)}</td>
                  <td className={candidate.risk_penalty >= 35 ? "text-danger" : "text-muted"}>{candidate.risk_penalty.toFixed(0)}</td>
                  <td className="max-w-[300px] text-muted">{candidate.evidence[0] ?? "等待更多证据"}</td>
                  <td>
                    <button
                      onClick={(event) => {
                        event.stopPropagation();
                        onToggleObserve(candidate);
                      }}
                      className={`rounded-md border px-2.5 py-1 text-xs font-semibold transition ${
                        candidate.observed ? "border-pine/30 bg-pine/10 text-pine" : "border-ink/10 bg-paper text-muted hover:text-pine"
                      }`}
                    >
                      {candidate.observed ? "观察中" : "加入观察"}
                    </button>
                  </td>
                </tr>
              ))}
              {candidates.length === 0 && (
                <tr>
                  <td colSpan={9} className="text-muted">
                    暂无潜伏候选。可以运行扫描；如果历史源不可用，会明确提示，不使用本地假候选。
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        <div className="rounded-lg border border-ink/10 bg-white p-4">
          {activeCandidate ? (
            <div>
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <p className="text-xs text-muted">{activeCandidate.symbol}</p>
                  <h3 className="mt-1 text-xl font-semibold text-ink">{activeCandidate.name}</h3>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <StageBadge stage={activeCandidate.stage} />
                  <button
                    onClick={() => onToggleObserve(activeCandidate)}
                    className={`rounded-md border px-2.5 py-1 text-xs font-semibold transition ${
                      activeCandidate.observed ? "border-pine/30 bg-pine/10 text-pine" : "border-ink/10 bg-paper text-muted hover:text-pine"
                    }`}
                  >
                    {activeCandidate.observed ? "观察中" : "加入观察"}
                  </button>
                  <button
                    onClick={() => onRunSymbolScan(activeCandidate.symbol)}
                    disabled={busy || scanRunning}
                    className="rounded-md border border-ink/10 bg-white px-2.5 py-1 text-xs font-semibold text-muted transition hover:border-pine/30 hover:text-pine disabled:opacity-50"
                  >
                    单票补扫
                  </button>
                </div>
              </div>
              <div className="mt-4 grid grid-cols-2 gap-2">
                <InfoBlock label="潜伏分" value={activeCandidate.accumulation_score.toFixed(0)} />
                <InfoBlock label="启动分" value={activeCandidate.launch_score.toFixed(0)} />
                <InfoBlock label="题材分" value={activeCandidate.theme_score.toFixed(0)} />
                <InfoBlock label="风险扣分" value={activeCandidate.risk_penalty.toFixed(0)} tone="danger" />
              </div>
              <div className="mt-4 h-48 rounded-lg border border-ink/10 bg-paper/60 p-3">
                {chartData.length ? (
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={chartData}>
                      <CartesianGrid stroke="#e4e0d7" strokeDasharray="3 3" />
                      <XAxis dataKey="date" tick={{ fontSize: 10 }} />
                      <YAxis tick={{ fontSize: 10 }} />
                      <Tooltip />
                      <Bar dataKey="close" fill="#0f5f57" radius={[3, 3, 0, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                ) : (
                  <div className="flex h-full items-center justify-center text-sm text-muted">选择候选后加载K线概览</div>
                )}
              </div>
              <div className="mt-4 space-y-2">
                {activeCandidate.evidence.map((item) => (
                  <p key={item} className="flex gap-2 text-xs leading-5 text-muted">
                    <CheckCircle2 className="mt-0.5 shrink-0 text-pine" size={14} />
                    {item}
                  </p>
                ))}
                {activeCandidate.risks.map((item) => (
                  <p key={item} className="flex gap-2 text-xs leading-5 text-danger">
                    <AlertTriangle className="mt-0.5 shrink-0" size={14} />
                    {item}
                  </p>
                ))}
              </div>
              <div className="mt-4 flex flex-wrap gap-2">
                {activeCandidate.themes.map((theme) => (
                  <span key={theme} className="rounded-md border border-signal/20 bg-signal/10 px-2 py-1 text-xs text-signal">
                    {theme}
                  </span>
                ))}
              </div>
            </div>
          ) : (
            <p className="text-sm leading-6 text-muted">运行扫描后，这里会显示候选详情、K线概览、题材共振和失效风险。</p>
          )}
        </div>
      </div>
    </section>
  );
}

function StealthMetric({ label, value, tone }: { label: string; value: string; tone?: "signal" | "danger" }) {
  const color = tone === "signal" ? "text-signal" : tone === "danger" ? "text-danger" : "text-ink";
  return (
    <div className="rounded-lg border border-ink/10 bg-white p-4">
      <p className="text-xs text-muted">{label}</p>
      <p className={`mt-1 text-2xl font-semibold ${color}`}>{value}</p>
    </div>
  );
}

function ScoreBadge({ value }: { value: number }) {
  const tone = value >= 75 ? "bg-pine/10 text-pine border-pine/20" : value >= 60 ? "bg-signal/10 text-signal border-signal/20" : "bg-paper text-muted border-ink/10";
  return <span className={`rounded-md border px-2 py-1 text-xs font-semibold ${tone}`}>{value.toFixed(0)}</span>;
}

function StageBadge({ stage }: { stage: StealthCandidate["stage"] }) {
  const tone =
    stage === "启动确认"
      ? "border-signal/25 bg-signal/10 text-signal"
      : stage === "潜伏观察"
        ? "border-pine/25 bg-pine/10 text-pine"
        : stage === "过热排除"
          ? "border-danger/25 bg-danger/10 text-danger"
          : "border-ink/10 bg-paper text-muted";
  return <span className={`rounded-md border px-2 py-1 text-xs font-semibold ${tone}`}>{stage}</span>;
}

function journalBucketTone(bucketKey: ObservationJournalEntry["bucket_key"]) {
  if (bucketKey === "activation") {
    return "border-signal/25 bg-signal/10 text-signal";
  }
  if (bucketKey === "invalid") {
    return "border-danger/25 bg-danger/10 text-danger";
  }
  if (bucketKey === "data_gap") {
    return "border-amber-200 bg-amber-50 text-amber-800";
  }
  return "border-pine/25 bg-pine/10 text-pine";
}

function PreopenPanel({ preopen }: { preopen: PreopenBrief }) {
  const items = [
    ...preopen.must_watch.map((item) => ({ ...item, lane: "必须关注" })),
    ...preopen.watchlist_impacts.map((item) => ({ ...item, lane: "自选股影响" })),
    ...preopen.risk_events.map((item) => ({ ...item, lane: "风险事件" }))
  ];

  return (
    <section className="panel rounded-lg p-5">
      <SectionTitle icon={CalendarClock} title="盘前 Brief" aside={`版本 ${preopen.version} / 就绪度 ${preopen.readiness}%`} />
      <div className="mt-4 grid grid-cols-1 gap-3 lg:grid-cols-2">
        {items.map((item) => (
          <BriefRow key={`${item.lane}-${item.title}`} item={item} lane={item.lane} />
        ))}
      </div>
      <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2">
        {preopen.sector_clues.concat(preopen.calendar).map((item) => (
          <div key={item.title} className="rounded-lg border border-ink/10 bg-white p-4">
            <p className="text-xs font-semibold text-signal">{item.impact_scope.join(" / ") || "实时行情"}</p>
            <h3 className="mt-2 text-sm font-semibold">{item.title}</h3>
            <p className="mt-2 text-sm leading-6 text-muted">{item.detail}</p>
          </div>
        ))}
      </div>
    </section>
  );
}

function RadarPanel({ events, snapshots }: { events: MarketEvent[]; snapshots: MarketSnapshot[] }) {
  const latestSnapshot = snapshots[snapshots.length - 1];
  return (
    <section className="panel rounded-lg p-5">
      <SectionTitle icon={Radio} title="盘中 Radar" aside={`${events.length} 条事件`} />
      <div className="mt-4 grid grid-cols-1 gap-3 md:grid-cols-4">
        <Metric label="5m 快照" value={snapshots.length.toString()} />
        <Metric label="最新记录" value={latestSnapshot ? formatTime(latestSnapshot.captured_at) : "--"} />
        <Metric label="市场温度" value={latestSnapshot ? latestSnapshot.market_temperature.score.toString() : "--"} />
        <Metric label="来源" value={latestSnapshot?.provider ?? "dev"} />
      </div>
      <div className="mt-5 grid grid-cols-1 gap-4 xl:grid-cols-2">
        {events.map((event) => (
          <article key={event.id} className="grid grid-cols-[76px_1fr] gap-3">
            <time className="pt-1 text-xs font-semibold text-muted">{formatTime(event.occurred_at)}</time>
            <div className="rounded-lg border border-ink/10 bg-white p-4">
              <div className="flex flex-wrap items-center gap-2">
                <Pill importance={event.importance} />
                <span className="rounded-md border border-ink/10 px-2 py-1 text-xs text-muted">{event.compliance_label}</span>
              </div>
              <h3 className="mt-3 text-base font-semibold">{event.title}</h3>
              <p className="mt-2 text-sm leading-6 text-muted">{event.summary}</p>
              {event.inference && <p className="mt-2 text-sm leading-6 text-signal">推断：{event.inference}</p>}
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}

function WatchlistPanel({
  watchlist,
  selectedSymbol,
  onSelect,
  onAdd,
  onDelete
}: {
  watchlist: WatchlistStock[];
  selectedSymbol: string;
  onSelect: (symbol: string) => void;
  onAdd: (payload: { symbol: string; group: string; tags: string[] }) => Promise<void>;
  onDelete: (symbol: string) => Promise<void>;
}) {
  const [symbol, setSymbol] = useState("");
  const [group, setGroup] = useState("核心观察");
  const [tags, setTags] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    if (!symbol.trim()) {
      setError("股票代码不能为空。");
      return;
    }
    setSaving(true);
    try {
      await onAdd({
        symbol: symbol.trim().toUpperCase(),
        group: group.trim() || "默认分组",
        tags: tags
          .split(/[,\s，、/]+/)
          .map((item) => item.trim())
          .filter(Boolean)
      });
      setSymbol("");
      setTags("");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "添加失败");
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="panel rounded-lg p-5">
      <SectionTitle icon={Bell} title="自选股中心" aside={`${watchlist.length}/50`} />
      <form onSubmit={submit} className="mt-4 grid grid-cols-1 gap-2 rounded-lg border border-ink/10 bg-white p-3 md:grid-cols-[1fr_1fr_1fr_auto]">
        <input
          value={symbol}
          onChange={(event) => setSymbol(event.target.value)}
          className="min-h-10 rounded-md border border-ink/10 px-3 text-sm outline-none focus:border-pine"
          placeholder="代码 例如 600000.SH"
        />
        <input
          value={group}
          onChange={(event) => setGroup(event.target.value)}
          className="min-h-10 rounded-md border border-ink/10 px-3 text-sm outline-none focus:border-pine"
          placeholder="分组"
        />
        <input
          value={tags}
          onChange={(event) => setTags(event.target.value)}
          className="min-h-10 rounded-md border border-ink/10 px-3 text-sm outline-none focus:border-pine"
          placeholder="标签，用逗号分隔"
        />
        <button
          type="submit"
          disabled={saving}
          className="inline-flex min-h-10 items-center justify-center gap-2 rounded-md bg-pine px-3 text-sm font-semibold text-white disabled:opacity-60"
        >
          {saving ? <RefreshCcw className="animate-spin" size={16} /> : <Plus size={16} />}
          添加
        </button>
        {error && <p className="text-xs text-danger md:col-span-4">{error}</p>}
      </form>
      <div className="mt-4 overflow-x-auto">
        <table className="dense-table min-w-[720px]">
          <thead>
            <tr>
              <th>标的</th>
              <th>分组</th>
              <th>价格</th>
              <th>涨跌</th>
              <th>量比</th>
              <th>最新事件</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {watchlist.map((stock) => (
              <tr
                key={stock.symbol}
                className={`transition hover:bg-pine/5 ${selectedSymbol === stock.symbol ? "bg-pine/10" : ""}`}
                onClick={() => onSelect(stock.symbol)}
              >
                <td>
                  <button className="text-left" title={`查看 ${stock.name}`}>
                    <span className="block font-semibold">{stock.name}</span>
                    <span className="text-xs text-muted">{stock.symbol}</span>
                  </button>
                </td>
                <td>{stock.group}</td>
                <td>{stock.price.toFixed(2)}</td>
                <td>
                  <Change value={stock.change_pct} />
                </td>
                <td>{stock.volume_ratio.toFixed(1)}</td>
                <td className="max-w-[280px] text-muted">{stock.latest_event}</td>
                <td>
                  <button
                    onClick={(event) => {
                      event.stopPropagation();
                      void onDelete(stock.symbol);
                    }}
                    className="inline-flex h-9 w-9 items-center justify-center rounded-md border border-danger/20 text-danger transition hover:bg-danger/10"
                    title={`删除 ${stock.name}`}
                  >
                    <Trash2 size={16} />
                  </button>
                </td>
              </tr>
            ))}
            {watchlist.length === 0 && (
              <tr>
                <td colSpan={7} className="text-muted">
                  暂无自选股。添加代码后会从真实行情源识别名称、价格和涨跌幅。
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function StockFocus({ stock, sectors }: { stock?: WatchlistStock; sectors: SectorSnapshot[] }) {
  if (!stock) {
    return (
      <section className="panel rounded-lg p-5">
        <SectionTitle icon={Search} title="个股追踪" aside="等待自选股" />
        <p className="mt-4 rounded-lg border border-ink/10 bg-white p-4 text-sm leading-6 text-muted">
          添加一只 A 股代码后，这里会显示由真实行情源返回的名称、价格、涨跌幅、量比和触发事件。
        </p>
      </section>
    );
  }

  const sectorData = sectors.map((sector) => ({ name: sector.name, change: sector.change_pct }));

  return (
    <section className="panel rounded-lg p-5">
      <SectionTitle icon={Search} title="个股追踪" aside={stock.symbol} />
      <div className="mt-4 flex flex-col justify-between gap-4 border-b border-ink/10 pb-4 md:flex-row md:items-end">
        <div>
          <h2 className="text-2xl font-semibold">{stock.name}</h2>
          <p className="mt-2 text-sm text-muted">{stock.attention_reason}</p>
        </div>
        <div className="text-left md:text-right">
          <p className="text-3xl font-semibold">{stock.price.toFixed(2)}</p>
          <Change value={stock.change_pct} />
        </div>
      </div>
      <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-[1fr_280px]">
        <div className="h-56 rounded-lg border border-ink/10 bg-white p-3">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={sectorData}>
              <CartesianGrid stroke="#e4e0d7" strokeDasharray="3 3" />
              <XAxis dataKey="name" tick={{ fontSize: 12 }} />
              <YAxis tick={{ fontSize: 12 }} />
              <Tooltip />
              <Bar dataKey="change" fill="#285f9f" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
        <div className="space-y-3">
          <InfoBlock label="标签" value={stock.tags.join(" / ") || "未设置"} />
          <InfoBlock label="风险" value={stock.risk_flags.join(" / ") || "暂无实时风险标签"} tone="danger" />
          <InfoBlock label="最新事件" value={stock.latest_event} />
        </div>
      </div>
    </section>
  );
}

function AssistantPanel({
  query,
  answer,
  asking,
  onQueryChange,
  onSubmit
}: {
  query: string;
  answer: AssistantAnswer | null;
  asking: boolean;
  onQueryChange: (value: string) => void;
  onSubmit: () => void;
}) {
  return (
    <section className="panel rounded-lg p-5">
      <SectionTitle icon={Bot} title="AI 研究助手" aside="引用 + 合规拦截" />
      <div className="mt-4 flex flex-col gap-3 sm:flex-row">
        <input
          value={query}
          onChange={(event) => onQueryChange(event.target.value)}
          className="min-h-11 flex-1 rounded-md border border-ink/10 bg-white px-3 text-sm outline-none transition focus:border-pine"
          placeholder="输入一个盘面问题"
        />
        <button
          onClick={onSubmit}
          disabled={asking}
          className="inline-flex min-h-11 items-center justify-center gap-2 rounded-md bg-pine px-4 text-sm font-semibold text-white transition hover:bg-[#0b514a] disabled:cursor-not-allowed disabled:opacity-60"
        >
          {asking ? <RefreshCcw className="animate-spin" size={17} /> : <Sparkles size={17} />}
          生成回答
        </button>
      </div>
      <div className="mt-4 rounded-lg border border-ink/10 bg-white p-4">
        {answer ? (
          <div>
            <div className="mb-3 flex flex-wrap items-center gap-2">
              <span className="rounded-md border border-pine/20 bg-pine/10 px-2 py-1 text-xs text-pine">置信度 {answer.confidence}</span>
              {answer.blocked_by_compliance && (
                <span className="rounded-md border border-danger/30 bg-danger/10 px-2 py-1 text-xs text-danger">已触发合规拦截</span>
              )}
            </div>
            <p className="text-sm leading-7 text-ink">{answer.answer}</p>
            <div className="mt-4 space-y-2">
              {answer.evidence.map((item) => (
                <p key={item} className="flex gap-2 text-xs leading-5 text-muted">
                  <CheckCircle2 className="mt-0.5 shrink-0 text-pine" size={14} />
                  {item}
                </p>
              ))}
            </div>
            <div className="mt-4 flex flex-wrap gap-2">
              {answer.citations.map((citation) => (
                <a
                  key={citation.id}
                  href={citation.url}
                  className="rounded-md border border-ink/10 bg-paper px-2 py-1 text-xs text-muted transition hover:text-pine"
                >
                  {citation.name}
                </a>
              ))}
            </div>
          </div>
        ) : (
          <p className="text-sm leading-6 text-muted">回答只基于当前已接入的真实行情与结构化事件；没有来源时会标注无法确认。</p>
        )}
      </div>
    </section>
  );
}

function DataStatusView({
  agents,
  sources,
  jobRuns,
  onRunJob
}: {
  agents: AgentStatusResponse;
  sources: SourceRef[];
  jobRuns: JobRun[];
  onRunJob: (jobName: string) => void;
}) {
  return (
    <div className="grid grid-cols-1 gap-5 xl:grid-cols-[1fr_0.85fr]">
      <div className="space-y-5">
        <AgentPanel agents={agents} />
        <DataSourceStatusPanel statuses={agents.data_source_statuses ?? []} />
        <JobRunsPanel jobRuns={jobRuns} onRunJob={onRunJob} />
      </div>
      <SourcePanel sources={sources} />
    </div>
  );
}

function JobRunsPanel({ jobRuns, onRunJob }: { jobRuns: JobRun[]; onRunJob: (jobName: string) => void }) {
  const jobs = [
    { name: "post_market_replay", label: "一键盘后复盘" },
    { name: "intraday_snapshot", label: "盘中快照" },
    { name: "close_snapshot", label: "收盘快照" },
    { name: "news_explain", label: "公告新闻" },
    { name: "daily_report", label: "每日报告" }
  ];
  return (
    <section className="panel rounded-lg p-5">
      <SectionTitle icon={Clock3} title="跟踪任务" aside={`${jobRuns.length} 条运行记录`} />
      <div className="mt-4 flex flex-wrap gap-2">
        {jobs.map((job) => (
          <button
            key={job.name}
            onClick={() => onRunJob(job.name)}
            className="inline-flex min-h-9 items-center gap-2 rounded-md border border-pine/25 bg-pine/5 px-3 text-xs font-semibold text-pine transition hover:border-pine/40 hover:bg-pine/10"
          >
            <PlayCircle size={14} />
            {job.label}
          </button>
        ))}
      </div>
      <div className="mt-4 space-y-2">
        {jobRuns.slice(0, 8).map((run) => (
          <div key={run.id} className="rounded-md border border-ink/10 bg-white px-3 py-2">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="text-sm font-semibold">{run.job_name}</span>
              <span className={`rounded-md border px-2 py-1 text-xs ${run.status === "failed" ? "border-danger/20 bg-danger/10 text-danger" : "border-pine/20 bg-pine/10 text-pine"}`}>
                {run.status}
              </span>
            </div>
            <p className="mt-1 break-words text-xs leading-5 text-muted">{run.error || run.message || "任务已记录"}</p>
            <p className="mt-1 text-[11px] text-muted">{formatDateTime(run.started_at)} / {Math.round((run.duration_ms ?? 0) / 1000)}s</p>
          </div>
        ))}
        {jobRuns.length === 0 && <p className="rounded-md border border-ink/10 bg-white px-3 py-3 text-sm text-muted">暂无任务运行记录，可以先手动运行一次盘中快照。</p>}
      </div>
    </section>
  );
}

function AgentPanel({ agents }: { agents: AgentStatusResponse }) {
  return (
    <section className="panel rounded-lg p-5">
      <SectionTitle icon={Database} title="Agent 状态" aside={`24h 失败 ${agents.failure_count_24h}`} />
      <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2">
        {agents.agents.map((agent) => (
          <article key={agent.name} className="rounded-lg border border-ink/10 bg-white p-4">
            <div className="flex items-start justify-between gap-3">
              <div>
                <h3 className="text-sm font-semibold">{agent.name}</h3>
                <p className="mt-1 text-xs leading-5 text-muted">{agent.purpose}</p>
              </div>
              <span className="rounded-md border border-pine/20 bg-pine/10 px-2 py-1 text-xs text-pine">{agent.status}</span>
            </div>
            <p className="mt-3 text-xs text-muted">{agent.latest_message}</p>
          </article>
        ))}
      </div>
    </section>
  );
}

function SourcePanel({ sources }: { sources: SourceRef[] }) {
  return (
    <section className="panel rounded-lg p-5">
      <SectionTitle icon={FileText} title="数据来源" aside={`${sources.length} 个`} />
      <div className="mt-4 space-y-3">
        {sources.map((source) => (
          <article key={source.id} className="rounded-lg border border-ink/10 bg-white p-4">
            <h3 className="text-sm font-semibold">{source.name}</h3>
            <p className="mt-2 text-xs leading-5 text-muted">{source.freshness}</p>
            <div className="mt-3 flex flex-wrap gap-2 text-xs">
              <span className="rounded-md border border-ink/10 bg-paper px-2 py-1 text-muted">{formatDateTime(source.as_of)}</span>
              <span className="rounded-md border border-signal/20 bg-signal/10 px-2 py-1 text-signal">{source.license}</span>
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}

function Metric({ label, value, tone }: { label: string; value: string; tone?: "up" | "down" }) {
  const color = tone === "up" ? "text-pine" : tone === "down" ? "text-danger" : "text-ink";
  return (
    <div className="rounded-lg border border-ink/10 bg-white px-3 py-2">
      <p className="text-xs text-muted">{label}</p>
      <p className={`mt-1 text-lg font-semibold ${color}`}>{value}</p>
    </div>
  );
}

function Change({ value }: { value: number }) {
  const positive = value >= 0;
  return (
    <span className={`inline-flex items-center gap-1 text-sm font-semibold ${positive ? "text-pine" : "text-danger"}`}>
      {positive ? <TrendingUp size={15} /> : <TrendingDown size={15} />}
      {positive ? "+" : ""}
      {value.toFixed(2)}%
    </span>
  );
}

function Pill({ importance }: { importance: Importance }) {
  return <span className={`rounded-md border px-2 py-1 text-xs ${importanceStyle[importance]}`}>{importance}</span>;
}

function BriefRow({ item, lane }: { item: BriefItem; lane: string }) {
  return (
    <article className="rounded-lg border border-ink/10 bg-white p-4">
      <div className="flex flex-wrap items-center gap-2">
        <span className="rounded-md bg-ink px-2 py-1 text-xs text-white">{lane}</span>
        <Pill importance={item.importance} />
      </div>
      <h3 className="mt-3 text-base font-semibold">{item.title}</h3>
      <p className="mt-2 text-sm leading-6 text-muted">{item.detail}</p>
    </article>
  );
}

function InfoBlock({ label, value, tone }: { label: string; value: string; tone?: "danger" }) {
  return (
    <div className="rounded-lg border border-ink/10 bg-white p-4">
      <p className="text-xs text-muted">{label}</p>
      <p className={`mt-2 text-sm leading-6 ${tone === "danger" ? "text-danger" : "text-ink"}`}>{value}</p>
    </div>
  );
}

function SectionTitle({
  icon: Icon,
  title,
  aside
}: {
  icon: LucideIcon;
  title: string;
  aside: string;
}) {
  return (
    <div className="flex items-center justify-between gap-4">
      <div className="flex items-center gap-2">
        <span className="flex h-9 w-9 items-center justify-center rounded-md bg-pine/10 text-pine">
          <Icon size={18} />
        </span>
        <h2 className="text-lg font-semibold">{title}</h2>
      </div>
      <span className="rounded-md border border-ink/10 bg-white px-2.5 py-1 text-xs text-muted">{aside}</span>
    </div>
  );
}

function formatTime(value: string) {
  return new Intl.DateTimeFormat("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone: "Asia/Shanghai"
  }).format(new Date(value));
}

function formatTradeDate(value: string) {
  return value.length >= 10 ? value.slice(5, 10) : value;
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
