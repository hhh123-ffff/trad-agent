# Strategy Backtest Quality Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a repeatable daily-bar strategy replay and quality workspace that measures 1/3/5/10-day outcomes without future leakage and keeps historical replay separate from live signal tracking.

**Architecture:** Add a pure backtest calculation module around the existing deterministic `evaluate_candidate()` strategy, a PostgreSQL repository for tasks/signals/funnel data, and a single-worker background task service. Expose persisted summaries through compatible FastAPI routes and render them in a compact strategy-quality section inside the existing stealth discovery workspace.

**Tech Stack:** FastAPI, Pydantic, PostgreSQL, pandas/numpy, pytest, Next.js, React, TypeScript, Recharts.

---

### Task 1: Define Backtest Models And Schema

**Files:**
- Modify: `backend/app/models.py`
- Modify: `backend/app/database.py`
- Create: `backend/app/strategy_backtest_repository.py`
- Test: `backend/tests/test_strategy_backtest_repository.py`

- [ ] **Step 1: Write failing repository tests**

Test creation/update/read of a backtest run, idempotent signal outcome upserts, funnel persistence, pagination, and live/replay origin separation.

- [ ] **Step 2: Run focused tests and verify missing APIs**

Run: `pytest backend/tests/test_strategy_backtest_repository.py -q`

Expected: collection failure for missing repository and models.

- [ ] **Step 3: Add models**

Add:

```python
StrategyBacktestRunStatus = Literal["queued", "running", "completed", "failed"]
StrategySignalOrigin = Literal["replay", "live"]

class StrategyBacktestRequest(BaseModel):
    start_date: date | None = None
    end_date: date | None = None
    symbols: list[str] = Field(default_factory=list)
    repeat_days: int = Field(default=3, ge=2, le=10)

class StrategyBacktestRun(BaseModel): ...
class StrategySignalOutcome(BaseModel): ...
class StrategyBacktestFunnel(BaseModel): ...
class StrategyBacktestDetail(BaseModel): ...
class StrategyLiveOutcomeSummary(BaseModel): ...
```

- [ ] **Step 4: Add tables and repository**

Create `strategy_backtest_runs`, `strategy_signal_outcomes`, and `strategy_backtest_funnel`. Add repository functions for task lifecycle, idempotent signal/funnel writes, summaries, filters, and unfinished-task failure recovery.

- [ ] **Step 5: Run focused tests**

Run: `pytest backend/tests/test_strategy_backtest_repository.py -q`

Expected: all pass.

- [ ] **Step 6: Commit**

```powershell
git add backend/app/models.py backend/app/database.py backend/app/strategy_backtest_repository.py backend/tests/test_strategy_backtest_repository.py
git commit -m "feat: persist strategy backtest results"
```

---

### Task 2: Implement Pure Outcome Calculations

**Files:**
- Create: `backend/app/strategy_backtest.py`
- Test: `backend/tests/test_strategy_backtest.py`

- [ ] **Step 1: Write failing pure calculation tests**

Cover:

- estimated float-cap formula;
- next-trading-day open entry;
- 1/3/5/10-day close return, maximum favorable excursion, maximum adverse excursion;
- mature/immature/invalid horizon states;
- no future bars included in signal evaluation;
- three-day same-stage duplicate suppression and stage-upgrade reset;
- equal-weight benchmark and excess return;
- summary confidence thresholds.

- [ ] **Step 2: Run and verify failure**

Run: `pytest backend/tests/test_strategy_backtest.py -q`

Expected: import failure.

- [ ] **Step 3: Implement pure helpers and replay**

Implement:

```python
HORIZONS = (1, 3, 5, 10)
estimate_float_market_cap_billion(bar: DailyBar) -> float | None
calculate_horizon_outcomes(...)
deduplicate_signals(...)
aggregate_signal_outcomes(...)
replay_symbol_history(...)
```

`replay_symbol_history()` must pass only `bars[:signal_index + 1]` into `evaluate_candidate()`, use no themes or active themes, and add explicit historical-data limitations.

- [ ] **Step 4: Run focused tests**

Run: `pytest backend/tests/test_strategy_backtest.py -q`

Expected: all pass.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/strategy_backtest.py backend/tests/test_strategy_backtest.py
git commit -m "feat: calculate strategy replay outcomes"
```

---

### Task 3: Build Background Backtest Task Flow

**Files:**
- Create: `backend/app/strategy_backtest_tasks.py`
- Modify: `backend/app/strategy_backtest_repository.py`
- Test: `backend/tests/test_strategy_backtest_tasks.py`

- [ ] **Step 1: Write failing task tests**

Cover completed run, per-symbol failure continuation, overall failure, progress updates, idempotent rerun, and unfinished-task recovery.

- [ ] **Step 2: Run and verify failure**

Run: `pytest backend/tests/test_strategy_backtest_tasks.py -q`

- [ ] **Step 3: Implement single-worker task**

Use a dedicated one-worker `ThreadPoolExecutor`. Load local database bars grouped by symbol once, replay each symbol, persist signals/funnel incrementally, aggregate results, and never call external providers.

- [ ] **Step 4: Run focused tests**

Run: `pytest backend/tests/test_strategy_backtest_tasks.py -q`

- [ ] **Step 5: Commit**

```powershell
git add backend/app/strategy_backtest_tasks.py backend/app/strategy_backtest_repository.py backend/tests/test_strategy_backtest_tasks.py
git commit -m "feat: run strategy backtests in background"
```

---

### Task 4: Track Live Signal Outcomes

**Files:**
- Modify: `backend/app/strategy_backtest.py`
- Modify: `backend/app/strategy_backtest_repository.py`
- Modify: `backend/app/tracking_service.py`
- Test: `backend/tests/test_strategy_backtest.py`
- Test: `backend/tests/test_tracking_service.py`

- [ ] **Step 1: Write failing live tracking tests**

Prove strict daily candidates are saved with `origin=live`, future outcomes refresh as bars mature, invalid/missing bars do not fabricate returns, and live tracking failure degrades the stealth step scope without breaking the deterministic report.

- [ ] **Step 2: Run and verify failure**

Run: `pytest backend/tests/test_strategy_backtest.py backend/tests/test_tracking_service.py -q`

- [ ] **Step 3: Implement live synchronization**

Add `sync_live_signal_outcomes(trading_day)` and call it after the post-market scan step. Keep live summaries separate from replay summaries.

- [ ] **Step 4: Run focused tests**

Run: `pytest backend/tests/test_strategy_backtest.py backend/tests/test_tracking_service.py -q`

- [ ] **Step 5: Commit**

```powershell
git add backend/app/strategy_backtest.py backend/app/strategy_backtest_repository.py backend/app/tracking_service.py backend/tests/test_strategy_backtest.py backend/tests/test_tracking_service.py
git commit -m "feat: track live strategy signal outcomes"
```

---

### Task 5: Expose Backtest APIs

**Files:**
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_api.py`

- [ ] **Step 1: Write failing API tests**

Cover run creation, latest/detail routes, signal filtering/pagination, funnel route, live-outcome route, invalid request ranges, unknown run, and low-confidence limitations.

- [ ] **Step 2: Run and verify route failures**

Run: `pytest backend/tests/test_api.py -q -k "strategy_backtest or live_outcome"`

- [ ] **Step 3: Implement routes**

Add:

```text
POST /api/strategy/backtests/run
GET /api/strategy/backtests/latest
GET /api/strategy/backtests/{run_id}
GET /api/strategy/backtests/{run_id}/signals
GET /api/strategy/backtests/{run_id}/funnel
GET /api/strategy/live-outcomes
```

- [ ] **Step 4: Run complete API tests**

Run: `pytest backend/tests/test_api.py -q`

- [ ] **Step 5: Commit**

```powershell
git add backend/app/main.py backend/tests/test_api.py
git commit -m "feat: expose strategy quality APIs"
```

---

### Task 6: Add Strategy Quality Workspace

**Files:**
- Modify: `lib/types.ts`
- Modify: `lib/api.ts`
- Create: `components/strategy/strategy-quality.tsx`
- Modify: `components/marketlens-dashboard.tsx`

- [ ] **Step 1: Extend frontend contracts**

Add types and API functions for run request/latest/detail/signals/funnel/live outcomes.

- [ ] **Step 2: Implement strategy-quality component**

Render:

- latest task status/date range/confidence/run action;
- mature sample count and 5-day median/benchmark/outperformance/drawdown metrics;
- 1/3/5/10-day compact table;
- stage comparison;
- funnel;
- recent signal outcomes;
- live outcome summary;
- fixed limitations and compliance disclosure;
- loading, empty, running, low-confidence, failed, and API-failure states.

- [ ] **Step 3: Integrate into stealth discovery**

Place the quality workspace before candidate operations so the user sees strategy evidence before current candidates.

- [ ] **Step 4: Build**

Run: `npm.cmd run build`

Expected: pass.

- [ ] **Step 5: Commit**

```powershell
git add lib/types.ts lib/api.ts components/strategy/strategy-quality.tsx components/marketlens-dashboard.tsx
git commit -m "feat: add strategy quality workspace"
```

---

### Task 7: Verify And Document

**Files:**
- Create: `tools/strategy_backtest_smoke.py`
- Modify: `package.json`
- Modify: `README.md`

- [ ] **Step 1: Add smoke command**

Run a bounded local backtest against a small symbol/date set, poll completion, print summary/funnel/sample signals, and fail only when task execution or persisted outputs fail.

- [ ] **Step 2: Document operation and limits**

Document run/API/UI workflow, next-open entry, historical float-cap estimate, sample confidence, and known biases.

- [ ] **Step 3: Run full verification**

```powershell
npm.cmd run test:api
npm.cmd run build
npm.cmd run smoke:backtest
python -m compileall -q backend/app
git diff --check
```

- [ ] **Step 4: Browser verification**

Inspect desktop and mobile stealth pages for no overlap or horizontal overflow and verify empty/running/completed/failed states.

- [ ] **Step 5: Compliance scan**

```powershell
rg -n "买入|卖出|持有|仓位建议|目标价|收益承诺|稳赚" backend/app components/strategy lib tools/strategy_backtest_smoke.py
```

Expected: only compliance/disclaimer references.

- [ ] **Step 6: Commit and push**

```powershell
git add tools/strategy_backtest_smoke.py package.json README.md
git commit -m "docs: complete strategy quality workflow"
git push origin codex/volume-price-strategy-ui
```
