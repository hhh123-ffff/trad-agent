# Daily Operational Loop Implementation Plan

> **Execution mode:** Implement inline with `superpowers:executing-plans`. Apply `superpowers:test-driven-development` to every behavior change and `superpowers:verification-before-completion` before claiming completion.

**Goal:** Turn `post_market_replay` into a durable six-step daily operating loop with retryable failures, freshness visibility, in-app notifications, step reruns, and a clear Data Status workspace.

**Architecture:** Keep the current synchronous FastAPI job entry and existing business services. Add durable step attempts and notifications around them, isolate orchestration/error classification/freshness logic into focused modules, and expose compatible detail APIs. The frontend consumes the richer job detail without changing existing report or scan routes.

**Tech stack:** FastAPI, Pydantic, PostgreSQL, Redis, pytest, Next.js, React, TypeScript, Tailwind CSS.

---

## Task 1: Persist Step Attempts And Notifications

**Files:**
- Modify: `backend/app/models.py`
- Modify: `backend/app/database.py`
- Modify: `backend/app/tracking_repository.py`
- Test: `backend/tests/test_tracking_repository.py`

### Step 1: Write failing repository tests

Add tests that prove:

- a job run accepts `degraded` and `skipped` terminal statuses;
- every step attempt is stored independently and listed in creation order;
- a notification can be created, listed, and marked read;
- job-run detail returns the top-level run plus all step attempts.

Use explicit test fixtures and assert complete serialized fields, including `attempt`, `duration_ms`, `error_code`, `retryable`, `metadata`, and `read_at`.

### Step 2: Run the focused tests and confirm failure

Run:

```powershell
pytest backend/tests/test_tracking_repository.py -q
```

Expected: failures for missing step/notification models and repository functions.

### Step 3: Add models and schema

In `backend/app/models.py`, add:

```python
JobRunStatus = Literal["queued", "running", "completed", "degraded", "failed", "skipped"]
JobRunStepStatus = Literal["pending", "running", "completed", "degraded", "failed", "skipped"]
NotificationType = Literal["pipeline_completed", "pipeline_degraded", "pipeline_failed", "data_stale"]
NotificationSeverity = Literal["info", "warning", "critical"]
```

Add `JobRunStep`, `JobRunDetail`, and `AppNotification` models. Keep existing `JobRun` fields compatible.

In `backend/app/database.py`, create:

- `job_run_steps` with a foreign key to `job_runs`, attempt/status/error/result fields, and indexes on `job_run_id` and `(job_run_id, step_name)`;
- `app_notifications` with related-run foreign key, JSON metadata, read timestamp, and indexes on `created_at` and `read_at`.

Use `CREATE TABLE IF NOT EXISTS` and compatible `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` changes.

### Step 4: Add repository operations

In `backend/app/tracking_repository.py`, add:

```python
create_job_run_step(...)
finish_job_run_step(...)
list_job_run_steps(job_run_id: str)
get_job_run_detail(job_run_id: str)
create_app_notification(...)
list_app_notifications(unread_only: bool = False, limit: int = 50)
mark_app_notification_read(notification_id: str)
```

Preserve step history: finishing or rerunning a step never overwrites a prior attempt.

### Step 5: Run focused tests

Run:

```powershell
pytest backend/tests/test_tracking_repository.py -q
```

Expected: all repository tests pass.

### Step 6: Commit

```powershell
git add backend/app/models.py backend/app/database.py backend/app/tracking_repository.py backend/tests/test_tracking_repository.py
git commit -m "feat: persist pipeline steps and notifications"
```

---

## Task 2: Build The Retryable Pipeline Runner

**Files:**
- Create: `backend/app/job_pipeline.py`
- Test: `backend/tests/test_job_pipeline.py`

### Step 1: Write failing pipeline tests

Cover:

- six ordered step definitions can be executed;
- successful steps produce one `completed` attempt;
- a temporary provider error succeeds on a later attempt and records every attempt;
- missing credentials and configuration errors do not retry;
- an exhausted retryable error ends as `failed`;
- an intentionally unavailable optional capability may return `degraded`;
- pipeline aggregation is `completed`, `degraded`, or `failed`, with `daily_report` failure always producing `failed`.

Stub sleep/backoff so tests remain fast.

### Step 2: Run and confirm failure

```powershell
pytest backend/tests/test_job_pipeline.py -q
```

Expected: import failure because `job_pipeline.py` does not exist.

### Step 3: Implement error classification and execution

Add:

```python
class StepOutcome:
    status: Literal["completed", "degraded", "skipped"]
    result_scope: dict[str, Any]
    warnings: list[str]

class ClassifiedStepError:
    code: str
    retryable: bool
    action: str

def classify_step_error(exc: Exception) -> ClassifiedStepError: ...
def run_pipeline_step(..., max_attempts: int = 3, sleep: Callable = time.sleep) -> StepOutcome: ...
def aggregate_pipeline_status(step_results: Sequence[JobRunStep]) -> JobRunStatus: ...
```

Classification rules:

- timeout/connection/temporary 5xx: `temporary_provider_error`, retryable;
- rate limiting: `rate_limit`, retryable;
- database/Redis write failure: `storage_error`, retryable;
- missing token/credentials: `missing_credentials`, not retryable;
- invalid configuration: `configuration_error`, not retryable;
- invalid provider payload: `data_contract_error`, not retryable;
- otherwise: `unknown_error`, not retryable.

Backoff must be short and bounded.

### Step 4: Run focused tests

```powershell
pytest backend/tests/test_job_pipeline.py -q
```

Expected: all pipeline tests pass.

### Step 5: Commit

```powershell
git add backend/app/job_pipeline.py backend/tests/test_job_pipeline.py
git commit -m "feat: add durable retryable job pipeline"
```

---

## Task 3: Evaluate Data Freshness

**Files:**
- Create: `backend/app/data_freshness.py`
- Modify: `backend/app/tracking_repository.py`
- Test: `backend/tests/test_data_freshness.py`

### Step 1: Write failing freshness tests

Cover `fresh`, `stale`, and `missing` for:

- market snapshot target date;
- latest daily bar date;
- announcement query window;
- deterministic daily report target date;
- Agent brief reference to the latest deterministic report.

Assert an overall result and per-scope actionable messages.

### Step 2: Run and confirm failure

```powershell
pytest backend/tests/test_data_freshness.py -q
```

Expected: import failure because freshness evaluator does not exist.

### Step 3: Implement evaluator

Add deterministic models:

```python
FreshnessStatus = Literal["fresh", "stale", "missing"]

class FreshnessCheck(BaseModel):
    scope: str
    status: FreshnessStatus
    expected_date: date
    actual_date: date | None
    message: str

class DataFreshnessResult(BaseModel):
    status: FreshnessStatus
    checks: list[FreshnessCheck]
```

Repository helpers must query the latest stored dates without fetching external data. The evaluator accepts a target date and returns a result suitable for storing under `affected_scope.data_freshness`.

### Step 4: Run focused tests

```powershell
pytest backend/tests/test_data_freshness.py -q
```

Expected: all freshness tests pass.

### Step 5: Commit

```powershell
git add backend/app/data_freshness.py backend/app/tracking_repository.py backend/tests/test_data_freshness.py
git commit -m "feat: evaluate daily data freshness"
```

---

## Task 4: Refactor Post-Market Replay Into Six Durable Steps

**Files:**
- Modify: `backend/app/tracking_service.py`
- Modify: `backend/app/notification_service.py` or create it if absent
- Modify: `backend/tests/test_tracking_service.py`

### Step 1: Write failing orchestration tests

Replace or extend current replay tests to prove:

- success executes the exact six-step order;
- a failed data step does not prevent later independent steps or `daily_report`;
- no THS token produces a degraded result and explicit data gap;
- temporary failure retries then succeeds;
- permanent configuration failure is attempted once;
- `daily_report` failure makes the top-level run `failed`;
- Agent step uses deterministic fallback when no model is configured;
- pipeline completion/degradation/failure creates the corresponding notification;
- stale freshness creates an additional `data_stale` notification.

### Step 2: Run and confirm failure

```powershell
pytest backend/tests/test_tracking_service.py -q
```

Expected: failures because replay is still monolithic and no durable step attempts exist.

### Step 3: Implement notification service

Add focused functions:

```python
create_pipeline_notification(job_run_detail: JobRunDetail) -> AppNotification
create_freshness_notification(job_run_id: str, freshness: DataFreshnessResult) -> AppNotification | None
```

Messages must explain the affected scope and next action without investment advice.

### Step 4: Implement six-step orchestration

Refactor `_post_market_replay_job()` to define and execute:

1. `close_snapshot`
2. `collect_information`
3. `stealth_scan`
4. `observation_journal`
5. `daily_report`
6. `agent_post_market`

Each step must delegate to existing business functions, return a compact `result_scope`, and be persisted through `job_pipeline.py`.

Update `run_tracking_job()` so a handler may return terminal status plus affected scope. Finish the top-level run as `completed`, `degraded`, `failed`, or `skipped` instead of treating every non-exception return as completed.

Evaluate freshness after step execution, store it in top-level `affected_scope`, and create notifications.

### Step 5: Run focused tests

```powershell
pytest backend/tests/test_tracking_service.py backend/tests/test_job_pipeline.py backend/tests/test_data_freshness.py -q
```

Expected: all focused tests pass.

### Step 6: Commit

```powershell
git add backend/app/tracking_service.py backend/app/notification_service.py backend/tests/test_tracking_service.py
git commit -m "feat: orchestrate durable post market replay"
```

---

## Task 5: Add Detail, Rerun, And Notification APIs

**Files:**
- Modify: `backend/app/main.py`
- Modify: `backend/app/tracking_service.py`
- Modify: `backend/tests/test_api.py`

### Step 1: Write failing API tests

Cover:

- `GET /api/admin/jobs/runs/{run_id}` returns run and step attempts;
- unknown run returns `404`;
- `POST /api/admin/jobs/runs/{run_id}/steps/{step_name}/rerun` executes only the target step and appends an attempt;
- rerun rejects unknown/non-rerunnable steps;
- `GET /api/admin/notifications` supports unread filtering;
- `POST /api/admin/notifications/{notification_id}/read` returns updated notification;
- unknown notification returns `404`.

### Step 2: Run and confirm failure

```powershell
pytest backend/tests/test_api.py -q
```

Expected: route `404` failures.

### Step 3: Implement service and routes

Add service functions that validate run/step existence, map the target step to its existing handler, execute only that step, append an attempt, refresh the parent run summary, and return current detail.

Add the four compatible routes specified by the design. Keep existing list/run routes unchanged.

### Step 4: Run focused tests

```powershell
pytest backend/tests/test_api.py -q
```

Expected: all API tests pass.

### Step 5: Commit

```powershell
git add backend/app/main.py backend/app/tracking_service.py backend/tests/test_api.py
git commit -m "feat: expose pipeline recovery APIs"
```

---

## Task 6: Protect Scheduled Runs On Non-Trading Days

**Files:**
- Modify: `backend/app/tracking_scheduler.py`
- Modify: `backend/app/tracking_service.py`
- Test: `backend/tests/test_tracking_scheduler.py`

### Step 1: Write failing scheduler tests

Cover:

- a scheduled weekday with recent market data runs normally;
- Saturday/Sunday produces a top-level `skipped` run with an explicit reason and no data steps;
- an unconfirmed trading day produces `skipped`, not silent omission;
- a manual run remains allowed for any date.

### Step 2: Run and confirm failure

```powershell
pytest backend/tests/test_tracking_scheduler.py -q
```

Expected: failures because scheduler currently relies only on cron weekdays.

### Step 3: Implement guard

Add a small trading-day guard that checks weekday plus the most recent stored market date. The scheduler invokes the protected entry; manual API calls invoke the unprotected entry.

When protected execution is skipped, persist a `skipped` top-level run with `affected_scope.skip_reason`.

### Step 4: Run focused tests

```powershell
pytest backend/tests/test_tracking_scheduler.py -q
```

Expected: all scheduler tests pass.

### Step 5: Commit

```powershell
git add backend/app/tracking_scheduler.py backend/app/tracking_service.py backend/tests/test_tracking_scheduler.py
git commit -m "feat: guard scheduled replay by trading day"
```

---

## Task 7: Build The Daily Operations Workspace

**Files:**
- Modify: `lib/types.ts`
- Modify: `lib/api.ts`
- Modify: `lib/job-status.ts`
- Create: `components/tracking/daily-operations.tsx`
- Modify: `components/marketlens-dashboard.tsx`
- Test: `lib/job-status.test.ts` or existing frontend test location

### Step 1: Add failing status transformation tests

Cover:

- all six steps are ordered consistently;
- latest attempt is shown while prior attempts remain available;
- `completed`, `degraded`, `failed`, `running`, `skipped`, and `pending` statuses map to stable labels/colors/actions;
- rerun action appears only for failed/degraded recoverable steps;
- freshness summary maps to `fresh`, `stale`, or `missing`.

Run the repository’s frontend test command if present; if none exists, keep transformation functions pure and verify them through TypeScript/build plus browser states.

### Step 2: Extend frontend types and API client

Add compatible `JobRunStatus`, `JobRunStep`, `JobRunDetail`, `AppNotification`, and freshness types. Add:

```typescript
getJobRunDetail(runId: string)
rerunJobStep(runId: string, stepName: string)
getNotifications(unreadOnly?: boolean)
markNotificationRead(notificationId: string)
```

Keep all existing API functions compatible.

### Step 3: Implement Daily Operations component

Create a compact trading-terminal workspace:

- header: target trading date, overall status, completion time, freshness;
- ordered six-step timeline: status, duration, attempts, result summary;
- failure/degradation detail: error category, action guidance, rerun button;
- notification list: unread/severity filters and mark-read action;
- explicit loading, empty, API failure, and rerun-in-progress states.

Use existing design tokens and Lucide icons. Avoid nested cards and horizontal overflow; mobile becomes one column.

### Step 4: Integrate into Data Status page

Replace the old summary-only job panel with the new workspace while preserving existing manual job controls and historical run list.

### Step 5: Build and inspect

```powershell
npm.cmd run build
```

Expected: TypeScript and Next.js build pass.

Start services if needed and inspect `http://127.0.0.1:3000` at desktop and mobile widths. Verify completed, degraded, failed, empty, and API-failure states without overlap.

### Step 6: Commit

```powershell
git add lib/types.ts lib/api.ts lib/job-status.ts components/tracking/daily-operations.tsx components/marketlens-dashboard.tsx
git commit -m "feat: add daily operations workspace"
```

---

## Task 8: Full Verification And Operational Smoke Test

**Files:**
- Modify: `tools/post_market_replay_smoke.py`
- Modify: `.env.example`
- Modify: `README.md`
- Test: `backend/tests`

### Step 1: Extend smoke test

Make `tools/post_market_replay_smoke.py`:

- trigger `post_market_replay`;
- poll/read its detail;
- print each of the six step statuses and attempts;
- print freshness and notification summary;
- exit non-zero only when the top-level status is `failed`, not when it is explicitly `degraded`.

### Step 2: Document daily operation

Document:

- scheduler remains disabled by default;
- how to run one manual daily loop;
- how to inspect and rerun a step;
- what `completed`, `degraded`, `failed`, and `skipped` mean;
- known free-source limitations and the no-investment-advice boundary.

### Step 3: Run full backend tests

```powershell
npm.cmd run test:api
```

Expected: all backend tests pass.

### Step 4: Run frontend production build

```powershell
npm.cmd run build
```

Expected: production build passes.

### Step 5: Run live smoke test

```powershell
npm.cmd run db:up
npm.cmd run smoke:replay
```

Expected: a durable six-step run is returned. Free-source or missing-token gaps may produce `degraded`, but the deterministic daily report must be present.

### Step 6: Review compliance and placeholders

Run:

```powershell
rg -n "买入|卖出|持有|仓位建议|目标价|收益承诺" backend components lib
rg -n "TODO|TBD|placeholder" backend/app components/tracking lib tools/post_market_replay_smoke.py
git diff --check
git status --short
```

Expected: no newly introduced investment advice, implementation placeholders, whitespace errors, or unexpected files.

### Step 7: Commit

```powershell
git add tools/post_market_replay_smoke.py .env.example README.md
git commit -m "docs: complete daily operations workflow"
```

### Step 8: Final review and push

Use `superpowers:requesting-code-review`, address actionable findings, rerun all verification, then push `codex/volume-price-strategy-ui`.
