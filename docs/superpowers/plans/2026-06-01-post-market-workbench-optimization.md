# Post-Market Workbench Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make MarketLens feel like a daily post-market research workbench: open the app, see whether data collection succeeded, read the full replay report, inspect news/announcement gaps, and move candidate stocks through an observation funnel.

**Architecture:** Preserve the existing FastAPI routes and Next.js app shell. Add typed backend status metadata for data-source capabilities, split the large dashboard component into focused view/components, and make Replay the primary workflow without changing the compliance boundary or adding trade advice.

**Tech Stack:** FastAPI, Pydantic, PostgreSQL/Redis, Next.js 16, React 19, TypeScript, Tailwind CSS, pytest, `npm.cmd run build`.

---

## Scope

In scope:
- Make the Replay/post-market page the primary daily workflow.
- Display `post_market_replay` as a step pipeline: snapshot, information, scan, observation journal, daily report.
- Add data-source capability/status metadata to the existing admin status response.
- Split the large React dashboard file around Replay, jobs, data sources, and reusable report sections.
- Add focused backend tests and TypeScript build validation.

Out of scope:
- Buying/selling/holding recommendations, target prices, position sizing, or return promises.
- Commercial authorization replacement for Tonghuashun/iFinD.
- A new scoring model for candidate discovery.
- A full design-system rewrite.

## File Structure

Create:
- `components/replay/daily-report.tsx`: render `DailyTrackingReport` headline, sections, metrics, evidence, warnings, and unavailable state.
- `components/replay/job-pipeline.tsx`: parse and render post-market job steps from `JobRun.affected_scope`.
- `components/replay/candidate-funnel.tsx`: summarize candidate stages and observation buckets using existing stealth data.
- `components/data-sources/data-source-status.tsx`: render provider capabilities, credential state, fallback state, and next action.
- `components/views/replay-view.tsx`: compose daily report, job pipeline, source status, and candidate funnel.
- `lib/job-status.ts`: pure helpers for extracting typed post-market job step state from `JobRun`.

Modify:
- `components/marketlens-dashboard.tsx`: make Replay the default workflow, pass data into `ReplayView`, and remove Replay/job/data-source rendering internals after extraction.
- `lib/types.ts`: add `DataSourceStatus` and optional `AgentStatusResponse.data_source_statuses`.
- `backend/app/models.py`: add `DataSourceStatus` and extend `AgentStatusResponse`.
- `backend/app/data_providers.py`: add `data_source_statuses()` helper built from configured providers and env state.
- `backend/app/main.py`: include `data_source_statuses` in `/api/admin/agents`.
- `backend/tests/test_data_providers.py`: cover Tonghuashun missing-token and fallback capability states.
- `backend/tests/test_api.py`: cover admin agent response compatibility.

## Task 1: Backend Data-Source Capability Contract

**Files:**
- Modify: `backend/app/models.py`
- Modify: `backend/app/data_providers.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_data_providers.py`
- Test: `backend/tests/test_api.py`

- [ ] **Step 1: Write failing provider-status tests**

Add these tests to `backend/tests/test_data_providers.py`:

```python
def test_tonghuashun_data_source_status_marks_missing_credentials(monkeypatch):
    from backend.app import data_providers

    monkeypatch.setenv("MARKETLENS_MARKET_PROVIDER", "ths")
    monkeypatch.setenv("MARKETLENS_HISTORY_PROVIDER", "ths_delayed")
    monkeypatch.setenv("MARKETLENS_INFO_PROVIDER", "ths")
    monkeypatch.delenv("THS_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("THS_REFRESH_TOKEN", raising=False)

    statuses = data_providers.data_source_statuses()
    by_id = {item.id: item for item in statuses}

    assert by_id["src-ths-quantapi-market"].status == "missing_credentials"
    assert by_id["src-ths-quantapi-market"].capabilities["quotes"] == "needs_token"
    assert by_id["src-ths-quantapi-delayed"].capabilities["history_bars"] == "needs_token"
    assert by_id["src-ths-quantapi-announcement"].capabilities["announcements"] == "needs_token"
    assert "THS_REFRESH_TOKEN" in by_id["src-ths-quantapi-market"].next_step


def test_tonghuashun_data_source_status_marks_configured_credentials(monkeypatch):
    from backend.app import data_providers

    monkeypatch.setenv("MARKETLENS_MARKET_PROVIDER", "ths")
    monkeypatch.setenv("MARKETLENS_HISTORY_PROVIDER", "ths_delayed")
    monkeypatch.setenv("MARKETLENS_INFO_PROVIDER", "ths")
    monkeypatch.setenv("THS_REFRESH_TOKEN", "dummy-refresh-token")
    monkeypatch.delenv("THS_ACCESS_TOKEN", raising=False)

    statuses = data_providers.data_source_statuses()
    by_id = {item.id: item for item in statuses}

    assert by_id["src-ths-quantapi-market"].status == "configured"
    assert by_id["src-ths-quantapi-market"].capabilities["quotes"] == "configured"
    assert by_id["src-ths-quantapi-delayed"].capabilities["stock_universe"] == "configured"
    assert by_id["src-ths-quantapi-announcement"].capabilities["news"] == "not_enabled"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
pytest backend\tests\test_data_providers.py::test_tonghuashun_data_source_status_marks_missing_credentials backend\tests\test_data_providers.py::test_tonghuashun_data_source_status_marks_configured_credentials -q
```

Expected: FAIL because `data_source_statuses` and `DataSourceStatus` do not exist.

- [ ] **Step 3: Add the Pydantic model**

In `backend/app/models.py`, add this model after `SourceRef`:

```python
class DataSourceStatus(BaseModel):
    id: str
    name: str
    provider: str
    status: Literal["configured", "missing_credentials", "fallback", "not_enabled"]
    capabilities: dict[str, str] = Field(default_factory=dict)
    latest_error: str | None = None
    last_success_at: datetime | None = None
    next_step: str = ""
```

Then extend `AgentStatusResponse`:

```python
class AgentStatusResponse(BaseModel):
    agents: list[AgentStatus]
    failure_count_24h: int
    data_sources: list[SourceRef]
    data_source_statuses: list[DataSourceStatus] = Field(default_factory=list)
```

- [ ] **Step 4: Add backend status helper**

In `backend/app/data_providers.py`, import `DataSourceStatus` from `.models` and add:

```python
def data_source_statuses() -> list[DataSourceStatus]:
    statuses: list[DataSourceStatus] = []
    ths_token_configured = bool(os.getenv("THS_ACCESS_TOKEN", "").strip() or os.getenv("THS_REFRESH_TOKEN", "").strip())
    ths_status = "configured" if ths_token_configured else "missing_credentials"
    ths_capability = "configured" if ths_token_configured else "needs_token"
    next_step = "" if ths_token_configured else "Set THS_REFRESH_TOKEN or THS_ACCESS_TOKEN, then rerun post_market_replay."

    if os.getenv("MARKETLENS_MARKET_PROVIDER", "dev").strip().lower() in {"ths", "ths_delayed", "ths_quantapi", "tonghuashun", "ifind"}:
        source = ths_market_source()
        statuses.append(DataSourceStatus(
            id=source.id,
            name=source.name,
            provider="ths-quantapi-market",
            status=ths_status,
            capabilities={
                "quotes": ths_capability,
                "indexes": ths_capability,
                "ranked_groups": ths_capability,
            },
            next_step=next_step,
        ))

    if os.getenv("MARKETLENS_HISTORY_PROVIDER", "dev").strip().lower() in {"ths", "ths_delayed", "ths_quantapi", "tonghuashun", "ifind"}:
        source = ths_delayed_source()
        statuses.append(DataSourceStatus(
            id=source.id,
            name=source.name,
            provider="ths-quantapi-delayed",
            status=ths_status,
            capabilities={
                "history_bars": ths_capability,
                "stock_universe": ths_capability,
                "theme_memberships": "fallback" if os.getenv("THS_THEME_FALLBACK_TO_AKSHARE", "1").strip() != "0" else "not_enabled",
            },
            next_step=next_step,
        ))

    if os.getenv("MARKETLENS_INFO_PROVIDER", "dev").strip().lower() in {"ths", "ths_quantapi", "tonghuashun", "ifind"}:
        source = ths_announcement_source()
        statuses.append(DataSourceStatus(
            id=source.id,
            name=source.name,
            provider="ths-quantapi-info",
            status=ths_status,
            capabilities={
                "announcements": ths_capability,
                "news": "not_enabled",
            },
            next_step=next_step or "News remains disabled until a licensed iFinD news endpoint is configured.",
        ))

    return statuses
```

- [ ] **Step 5: Include statuses in the admin route**

In `backend/app/main.py`, import `data_source_statuses` and update `agent_status()`:

```python
return {
    "agents": agents,
    "failure_count_24h": sum(agent.failure_count_24h for agent in agents),
    "data_sources": [*market_provider_sources(), *history_provider_sources(), *information_provider_sources()],
    "data_source_statuses": data_source_statuses(),
}
```

- [ ] **Step 6: Add API compatibility test**

Add to `backend/tests/test_api.py`:

```python
def test_admin_agents_includes_data_source_statuses():
    with TestClient(app) as client:
        response = client.get("/api/admin/agents")

    assert response.status_code == 200
    payload = response.json()
    assert "data_sources" in payload
    assert "data_source_statuses" in payload
    assert isinstance(payload["data_source_statuses"], list)
```

- [ ] **Step 7: Verify backend**

Run:

```powershell
npm.cmd run test:api
```

Expected: all backend tests pass.

## Task 2: Typed Job Pipeline Helpers

**Files:**
- Create: `lib/job-status.ts`
- Modify: `lib/types.ts`
- Use later from: `components/replay/job-pipeline.tsx`

- [ ] **Step 1: Add frontend types**

In `lib/types.ts`, add:

```ts
export interface DataSourceStatus {
  id: string;
  name: string;
  provider: string;
  status: "configured" | "missing_credentials" | "fallback" | "not_enabled";
  capabilities: Record<string, string>;
  latest_error: string | null;
  last_success_at: string | null;
  next_step: string;
}
```

Then extend `AgentStatusResponse`:

```ts
export interface AgentStatusResponse {
  agents: AgentStatus[];
  failure_count_24h: number;
  data_sources: SourceRef[];
  data_source_statuses?: DataSourceStatus[];
}
```

- [ ] **Step 2: Create job parsing helper**

Create `lib/job-status.ts`:

```ts
import type { JobRun } from "@/lib/types";

export type PipelineStatus = "completed" | "failed" | "skipped" | "pending";

export interface JobPipelineStep {
  key: "snapshot" | "information" | "scan" | "observation_journal" | "report";
  label: string;
  status: PipelineStatus;
  detail: string;
}

function scopeObject(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
}

function text(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value : fallback;
}

function numberText(value: unknown): string {
  return typeof value === "number" ? value.toString() : "0";
}

export function latestPostMarketRun(jobRuns: JobRun[]): JobRun | null {
  return jobRuns.find((run) => run.job_name === "post_market_replay") ?? null;
}

export function postMarketPipeline(run: JobRun | null): JobPipelineStep[] {
  const scope = scopeObject(run?.affected_scope);
  const snapshot = scopeObject(scope.snapshot);
  const information = scopeObject(scope.information);
  const scan = scopeObject(scope.scan);

  return [
    {
      key: "snapshot",
      label: "行情快照",
      status: text(snapshot.status, run ? "pending" : "pending") as PipelineStatus,
      detail: text(snapshot.error) || `事件 ${numberText(snapshot.events ?? scope.events)}`,
    },
    {
      key: "information",
      label: "新闻公告",
      status: text(information.status, run ? "pending" : "pending") as PipelineStatus,
      detail: text(information.error) || `新闻 ${numberText(information.news ?? scope.news)} / 公告 ${numberText(information.announcements ?? scope.announcements)}`,
    },
    {
      key: "scan",
      label: "潜力股扫描",
      status: text(scan.status, run ? "pending" : "pending") as PipelineStatus,
      detail: text(scan.error) || text(scan.reason) || `扫描 ${numberText(scan.scanned)} / 保存 ${numberText(scan.saved)}`,
    },
    {
      key: "observation_journal",
      label: "观察池日志",
      status: typeof scope.observation_journal === "number" ? "completed" : "pending",
      detail: `记录 ${numberText(scope.observation_journal)}`,
    },
    {
      key: "report",
      label: "每日报告",
      status: typeof scope.report_sections === "number" ? "completed" : "pending",
      detail: `板块 ${numberText(scope.report_sections)}`,
    },
  ];
}
```

- [ ] **Step 3: Type-check through build**

Run:

```powershell
npm.cmd run build
```

Expected: TypeScript build passes.

## Task 3: Extract Replay Report And Job Components

**Files:**
- Create: `components/replay/daily-report.tsx`
- Create: `components/replay/job-pipeline.tsx`
- Modify: `components/marketlens-dashboard.tsx`

- [ ] **Step 1: Move daily report rendering**

Create `components/replay/daily-report.tsx` by moving these existing functions from `components/marketlens-dashboard.tsx` without changing behavior:

```ts
DailyReportSection
DailyReportUnavailable
formatMetricValue
formatDateTime
```

Export:

```ts
export function DailyReportCard({
  trackingDaily,
  trackingError,
  jobRuns,
}: {
  trackingDaily?: DailyTrackingReport;
  trackingError?: string;
  jobRuns: JobRun[];
}) {
  // Use the existing ReplayPanel daily-report markup.
}
```

Keep imports local:

```ts
import type { DailyTrackingReport, JobRun } from "@/lib/types";
```

- [ ] **Step 2: Move job strip into pipeline component**

Create `components/replay/job-pipeline.tsx`:

```ts
import { CheckCircle2, CircleDashed, Clock3, XCircle } from "lucide-react";
import { latestPostMarketRun, postMarketPipeline, type PipelineStatus } from "@/lib/job-status";
import type { JobRun } from "@/lib/types";

export function PostMarketPipeline({ jobRuns }: { jobRuns: JobRun[] }) {
  const run = latestPostMarketRun(jobRuns);
  const steps = postMarketPipeline(run);

  return (
    <div className="grid gap-2 md:grid-cols-5">
      {steps.map((step) => (
        <div key={step.key} className="rounded-md border border-ink/10 bg-white px-3 py-3">
          <div className="flex items-center gap-2 text-sm font-semibold text-ink">
            <PipelineIcon status={step.status} />
            <span>{step.label}</span>
          </div>
          <p className="mt-2 line-clamp-3 text-xs leading-5 text-muted">{step.detail}</p>
        </div>
      ))}
    </div>
  );
}

function PipelineIcon({ status }: { status: PipelineStatus }) {
  if (status === "completed") return <CheckCircle2 className="h-4 w-4 text-signal" />;
  if (status === "failed") return <XCircle className="h-4 w-4 text-danger" />;
  if (status === "skipped") return <CircleDashed className="h-4 w-4 text-muted" />;
  return <Clock3 className="h-4 w-4 text-muted" />;
}
```

- [ ] **Step 3: Replace old ReplayPanel internals**

In `components/marketlens-dashboard.tsx`, change `ReplayPanel` to compose:

```tsx
function ReplayPanel({ replay, trackingDaily, jobRuns, trackingError }: {
  replay: ReplayReport;
  trackingDaily?: DailyTrackingReport;
  jobRuns: JobRun[];
  trackingError?: string;
}) {
  return (
    <div className="grid gap-5">
      <SectionTitle icon={PlayCircle} title="盘后 Replay" aside={replay.trading_day} />
      <PostMarketPipeline jobRuns={jobRuns} />
      <DailyReportCard trackingDaily={trackingDaily} trackingError={trackingError} jobRuns={jobRuns} />
    </div>
  );
}
```

- [ ] **Step 4: Verify frontend build**

Run:

```powershell
npm.cmd run build
```

Expected: build succeeds and no duplicate function names remain.

## Task 4: Make Replay The Primary Workbench

**Files:**
- Create: `components/replay/candidate-funnel.tsx`
- Create: `components/data-sources/data-source-status.tsx`
- Create: `components/views/replay-view.tsx`
- Modify: `components/marketlens-dashboard.tsx`

- [ ] **Step 1: Create candidate funnel component**

Create `components/replay/candidate-funnel.tsx`:

```tsx
import type { ObservationSummary, StealthCandidate } from "@/lib/types";

export function CandidateFunnel({
  candidates,
  observationSummary,
}: {
  candidates: StealthCandidate[];
  observationSummary?: ObservationSummary;
}) {
  const dataGap = candidates.filter((item) => item.stage === "数据不足").length;
  const accumulation = candidates.filter((item) => item.stage === "潜伏观察").length;
  const launch = candidates.filter((item) => item.stage === "启动确认").length;
  const overheated = candidates.filter((item) => item.stage === "过热排除").length;

  const rows = [
    { label: "数据可用", value: Math.max(candidates.length - dataGap, 0), detail: `缺口 ${dataGap}` },
    { label: "潜伏观察", value: accumulation, detail: "形态和量能进入观察" },
    { label: "启动确认", value: launch, detail: "强度改善但仍需复盘验证" },
    { label: "风险排除", value: overheated, detail: "过热或数据不足" },
    { label: "观察池", value: observationSummary?.total ?? 0, detail: `继续 ${observationSummary?.continue_count ?? 0} / 激活 ${observationSummary?.activation_count ?? 0}` },
  ];

  return (
    <div className="grid gap-2 md:grid-cols-5">
      {rows.map((row) => (
        <div key={row.label} className="rounded-md border border-ink/10 bg-white px-3 py-3">
          <p className="text-xs text-muted">{row.label}</p>
          <p className="mt-1 text-2xl font-semibold text-ink">{row.value}</p>
          <p className="mt-1 text-xs leading-5 text-muted">{row.detail}</p>
        </div>
      ))}
    </div>
  );
}
```

- [ ] **Step 2: Create data-source status component**

Create `components/data-sources/data-source-status.tsx`:

```tsx
import { AlertTriangle, CheckCircle2, CircleDashed } from "lucide-react";
import type { DataSourceStatus } from "@/lib/types";

export function DataSourceStatusPanel({ statuses }: { statuses: DataSourceStatus[] }) {
  if (statuses.length === 0) {
    return null;
  }

  return (
    <div className="grid gap-2 md:grid-cols-3">
      {statuses.map((source) => (
        <div key={source.id} className="rounded-md border border-ink/10 bg-white px-3 py-3">
          <div className="flex items-start justify-between gap-3">
            <div>
              <p className="text-sm font-semibold text-ink">{source.name}</p>
              <p className="mt-1 text-xs text-muted">{source.provider}</p>
            </div>
            <SourceStatusIcon status={source.status} />
          </div>
          <div className="mt-3 flex flex-wrap gap-1">
            {Object.entries(source.capabilities).map(([name, status]) => (
              <span key={name} className="rounded-md border border-ink/10 bg-fog px-2 py-1 text-[11px] text-muted">
                {name}: {status}
              </span>
            ))}
          </div>
          {source.next_step && <p className="mt-3 text-xs leading-5 text-muted">{source.next_step}</p>}
        </div>
      ))}
    </div>
  );
}

function SourceStatusIcon({ status }: { status: DataSourceStatus["status"] }) {
  if (status === "configured") return <CheckCircle2 className="h-4 w-4 text-signal" />;
  if (status === "missing_credentials") return <AlertTriangle className="h-4 w-4 text-danger" />;
  return <CircleDashed className="h-4 w-4 text-muted" />;
}
```

- [ ] **Step 3: Compose ReplayView**

Create `components/views/replay-view.tsx`:

```tsx
import type {
  AgentStatusResponse,
  DailyTrackingReport,
  JobRun,
  ObservationSummary,
  ReplayReport,
  StealthCandidate,
} from "@/lib/types";
import { DataSourceStatusPanel } from "@/components/data-sources/data-source-status";
import { CandidateFunnel } from "@/components/replay/candidate-funnel";
import { DailyReportCard } from "@/components/replay/daily-report";
import { PostMarketPipeline } from "@/components/replay/job-pipeline";

export function ReplayView({
  replay,
  trackingDaily,
  jobRuns,
  trackingError,
  candidates,
  observationSummary,
  agents,
}: {
  replay: ReplayReport;
  trackingDaily?: DailyTrackingReport;
  jobRuns: JobRun[];
  trackingError?: string;
  candidates: StealthCandidate[];
  observationSummary?: ObservationSummary;
  agents?: AgentStatusResponse;
}) {
  return (
    <div className="grid gap-5">
      <PostMarketPipeline jobRuns={jobRuns} />
      <DailyReportCard trackingDaily={trackingDaily} trackingError={trackingError} jobRuns={jobRuns} />
      <CandidateFunnel candidates={candidates} observationSummary={observationSummary} />
      <DataSourceStatusPanel statuses={agents?.data_source_statuses ?? []} />
    </div>
  );
}
```

- [ ] **Step 4: Make Replay the default view**

In `components/marketlens-dashboard.tsx`, change:

```ts
function viewFromHash(): ViewId {
  const hash = window.location.hash.replace("#", "") as ViewId;
  return VIEW_ITEMS.some((item) => item.id === hash) ? hash : "replay";
}
```

Move the Replay nav item before Overview in `VIEW_ITEMS`, keeping all existing routes/hash IDs unchanged.

- [ ] **Step 5: Replace ReplayPanel use**

Replace the existing Replay branch with:

```tsx
{activeView === "replay" && (
  replay ? (
    <ReplayView
      replay={replay}
      trackingDaily={state.trackingDaily}
      jobRuns={state.jobRuns ?? []}
      trackingError={state.error}
      candidates={state.stealthCandidates ?? []}
      observationSummary={state.stealthObservationSummary}
      agents={state.agents}
    />
  ) : (
    <MarketUnavailableNotice error={state.error} onRefresh={() => void refresh()} />
  )
)}
```

- [ ] **Step 6: Verify workbench build**

Run:

```powershell
npm.cmd run build
```

Expected: build succeeds and Replay opens as the default view when no hash is present.

## Task 5: Keep Data Status As The Manual Control Room

**Files:**
- Modify: `components/marketlens-dashboard.tsx`
- Use: `components/data-sources/data-source-status.tsx`

- [ ] **Step 1: Reuse provider status in DataStatusView**

Change `DataStatusView` props to accept `agents?: AgentStatusResponse` or `dataSourceStatuses?: DataSourceStatus[]`, then render:

```tsx
<DataSourceStatusPanel statuses={agents?.data_source_statuses ?? []} />
```

Place it above `JobRunsPanel` so the user sees credential/data-source state before running jobs.

- [ ] **Step 2: Keep manual jobs unchanged**

Keep these job buttons in `JobRunsPanel`:

```ts
const jobs = [
  { name: "post_market_replay", label: "一键盘后复盘" },
  { name: "intraday_snapshot", label: "盘中快照" },
  { name: "close_snapshot", label: "收盘快照" },
  { name: "news_explain", label: "公告新闻" },
  { name: "daily_report", label: "每日报告" },
];
```

- [ ] **Step 3: Verify data status page**

Run:

```powershell
npm.cmd run build
```

Expected: build succeeds and Data Status still exposes all manual job buttons.

## Task 6: End-To-End Validation

**Files:**
- No new production files.
- Verify: backend tests, frontend build, manual job run.

- [ ] **Step 1: Run full backend test suite**

Run:

```powershell
npm.cmd run test:api
```

Expected: all tests pass.

- [ ] **Step 2: Run frontend build**

Run:

```powershell
npm.cmd run build
```

Expected: build succeeds.

- [ ] **Step 3: Run no-token Tonghuashun replay smoke test**

Run:

```powershell
$env:MARKETLENS_MARKET_PROVIDER='ths'
$env:MARKETLENS_HISTORY_PROVIDER='ths_delayed'
$env:MARKETLENS_INFO_PROVIDER='ths'
$env:MARKETLENS_POST_MARKET_ENABLE_SCAN='0'
python -c "from backend.app.repositories import ensure_storage; ensure_storage(); from backend.app.tracking_service import run_tracking_job; run=run_tracking_job('post_market_replay'); print(run.model_dump_json(indent=2))"
```

Expected:
- `status` is `completed`
- `affected_scope.snapshot.status` is `failed`
- `affected_scope.information.status` is `failed`
- `affected_scope.report_sections` is `6`
- `message` says the job partially completed from available data

- [ ] **Step 4: Run optional token-enabled Tonghuashun smoke test**

Only run this if `THS_REFRESH_TOKEN` or `THS_ACCESS_TOKEN` is configured:

```powershell
$env:MARKETLENS_POST_MARKET_ENABLE_SCAN='0'
python -c "from backend.app.repositories import ensure_storage; ensure_storage(); from backend.app.tracking_service import run_tracking_job; run=run_tracking_job('post_market_replay'); print(run.model_dump_json(indent=2))"
```

Expected:
- `affected_scope.snapshot.status` is `completed`
- `affected_scope.information.status` is `completed` or clearly reports an entitlement error
- Replay page shows provider capabilities and the latest pipeline state

## Self-Review Checklist

- Spec coverage: The plan covers Replay-first workflow, job pipeline, source capability visibility, candidate funnel, component split, and validation.
- Placeholder scan: No unresolved placeholder or undefined feature slots are used.
- Type consistency: Backend `DataSourceStatus` matches frontend `DataSourceStatus`; `AgentStatusResponse.data_source_statuses` is optional on the frontend for compatibility.
- Risk handling: Existing API routes remain unchanged; `data_sources` stays in the admin response; compliance boundary remains unchanged.
- Git note: This workspace currently appears to lack `.git` metadata, so commit steps should be skipped unless the repository metadata is restored.
