# MarketLens 盘面助手

A股盘前参考与盘后复盘 SaaS 的可运行实现。当前版本包含 FastAPI 后端、Next.js Web/PWA 前端、Docker PostgreSQL/Redis、真实行情源接入、Agent 状态、合规拦截、盘前 Brief、盘中 Radar、盘后 Replay、自选股中心和基于引用的 AI 问答。

## Run locally

```bash
npm install
npm run db:up
python -m pip install -r backend/requirements.txt
npm run api
npm run dev
```

Open `http://127.0.0.1:3000`.

API docs are available at `http://127.0.0.1:8000/docs`.

## Tonghuashun local replay loop

For the post-market replay workflow, start the API in Tonghuashun/iFinD mode:

```bash
npm run db:up
npm run api:ths
npm run dev
```

Then run a smoke replay without the bounded full-market scan:

```bash
npm run smoke:replay
```

Use this command only after Tonghuashun credentials and database performance are stable enough for candidate scanning:

```bash
npm run smoke:replay:scan
```

`api:ths` defaults to pure Tonghuashun mode by setting `THS_HISTORY_FALLBACK_TO_AKSHARE=0` and `THS_THEME_FALLBACK_TO_AKSHARE=0`. Set `THS_REFRESH_TOKEN` or `THS_ACCESS_TOKEN` before running it with real iFinD access. Without credentials, the replay smoke still generates the daily report and marks Tonghuashun sources as data gaps.

## Verify

```bash
npm run test:api
npm run build
```

## Architecture

- `backend/app/main.py`: FastAPI routes for dashboard, pre-open brief, radar events, replay, watchlist, stock profile, assistant, compliance, and admin agent status.
- `backend/app/market_provider.py`: live A-share market adapter. The current development adapter reads Eastmoney first, falls back to Sina Finance real quotes when needed, and raises `503` only when live sources are unavailable.
- `backend/app/history_provider.py`: AKShare-based research adapter for 250-day daily bars, weekly bars, stock universe, and concept membership.
- `backend/app/stealth_scanner.py`: long-horizon candidate scoring for accumulation, launch confirmation, theme resonance, and risk penalties.
- `backend/app/stealth_tasks.py`: background stealth scan runner. It creates a persisted task, runs the scan off the request thread, and updates progress for polling.
- `backend/app/agent_status.py`: operational Agent status for collector, quality, pre-open, radar, replay, and compliance jobs.
- `backend/app/compliance.py`: blocks buy/sell, position, target-price, guaranteed-return, and recommendation language.
- `backend/app/database.py`: PostgreSQL and Redis connections, schema initialization, and service health checks.
- `backend/app/repositories.py`: persistent watchlist, source metadata, and assistant-audit reads/writes.
- `app/` and `components/`: Next.js SaaS interface with PWA manifest, grouped left navigation, charts, timelines, watchlist, and assistant panel.

## Production replacement points

- Replace the Eastmoney/Sina development adapters in `backend/app/market_provider.py` with licensed data adapters for exchange 行情、公告、新闻、龙虎榜、资金流 and fundamentals before commercial use.
- Replace the AKShare research adapter in `backend/app/history_provider.py` with licensed historical行情、周线、题材 and membership data before commercial use.
- Keep PostgreSQL as the product database; add TimescaleDB/ClickHouse only after行情和事件量确实需要.
- Move Agent jobs to APScheduler/Celery/Redis or Temporal and wire alerting to the admin status endpoint.
- Connect the assistant to a real retrieval layer, but keep the current citation and compliance contract unchanged.
- Keep the boundary: information organization only, no investment advice, no target price, no position sizing, no trading account access.

## Local data services

`docker-compose.yml` starts:

- PostgreSQL on `127.0.0.1:5432`, database `qrant_agent`
- Redis on `127.0.0.1:6380` to avoid clashing with other local Redis instances

The API initializes tables on startup but does not seed demo market data. Dashboard, brief, radar, replay, stock profile, and assistant answers are built from live market responses; when the live source is unavailable, the API returns `503` instead of falling back to local fake data. Watchlist CRUD, source metadata, and assistant audit logs are persisted in PostgreSQL. Redis is used for lightweight runtime cache such as watchlist counts.

## Tonghuashun/iFinD data source

MarketLens can run Tonghuashun/iFinD first for market snapshots, historical K-lines, stock universe, and announcement collection:

```bash
MARKETLENS_MARKET_PROVIDER=ths
MARKETLENS_HISTORY_PROVIDER=ths_delayed
MARKETLENS_INFO_PROVIDER=ths
THS_QUANTAPI_BASE_URL=https://quantapi.51ifind.com/api/v1
THS_REFRESH_TOKEN=your_refresh_token
THS_ACCESS_TOKEN=
THS_HISTORY_FALLBACK_TO_AKSHARE=1
THS_THEME_FALLBACK_TO_AKSHARE=1
THS_MARKET_MAX_UNIVERSE_QUOTES=6000
THS_QUOTE_BATCH_SIZE=300
THS_UNIVERSE_SEARCHSTRING=全部A股
```

The HTTP adapter calls QuantAPI `get_access_token`, `real_time_quotation`, `cmd_history_quotation`, `smart_stock_picking`, and `report_query`. It stores normalized quote fields, OHLCV, announcement title/link metadata, and source ids. News remains a visible data gap until a specific licensed iFinD news endpoint is enabled; announcements are handled through `report_query`.

## Optional Tushare information fallback

Tushare Pro can still be used as a non-default information fallback:

```bash
MARKETLENS_INFO_PROVIDER=tushare
TUSHARE_TOKEN=your_token
TUSHARE_API_URL=http://api.tushare.pro
TUSHARE_NEWS_SRC=sina
```

The provider calls Tushare Pro `news` and `anns_d`, stores only title, summary, source link, source id, and publish time, and keeps the existing compliance boundary unchanged.

## One-click post-market replay

Use `POST /api/admin/jobs/run/post_market_replay` or the “数据状态 → 一键盘后复盘” button to run the MVP close loop:

- capture the post-market snapshot;
- collect news and announcements;
- run a bounded stealth scan;
- snapshot the observation journal;
- regenerate the daily tracking report.

The scan is intentionally bounded by default so local manual runs do not block on a full A-share pass:

```bash
MARKETLENS_POST_MARKET_ENABLE_SCAN=1
MARKETLENS_POST_MARKET_SCAN_LIMIT=500
MARKETLENS_POST_MARKET_SCAN_OFFSET=0
```

Set `MARKETLENS_POST_MARKET_SCAN_LIMIT=full` after the database and data provider are stable enough for a full-market scan.

## Daily operational loop

The Data Status page now exposes a durable six-step post-market loop:

1. `close_snapshot`
2. `collect_information`
3. `stealth_scan`
4. `observation_journal`
5. `daily_report`
6. `agent_post_market`

Run it manually:

```bash
curl -X POST http://127.0.0.1:8000/api/admin/jobs/run/post_market_replay
```

Inspect a run and rerun a failed or degraded step:

```bash
curl http://127.0.0.1:8000/api/admin/jobs/runs/<run_id>
curl -X POST http://127.0.0.1:8000/api/admin/jobs/runs/<run_id>/steps/collect_information/rerun
```

`completed` means all steps and freshness checks passed. `degraded` means the deterministic daily report is available but one or more sources, optional steps, or freshness checks have gaps. `failed` means the deterministic daily report could not be generated. `skipped` records an intentional scheduler guard or disabled capability.

The scheduler remains disabled by default. Set `MARKETLENS_ENABLE_SCHEDULER=1` only for an always-on local deployment. Scheduled post-market replay records an explicit skipped run on weekends or when the current market date cannot be confirmed. Manual runs remain available for recovery and testing.

All outputs remain research-only fact organization, structured replay, and risk disclosure. They do not provide buy/sell instructions, target prices, position sizing, or return promises.

## Stealth Discovery

The `#stealth` page adds a research-only candidate scanner for “潜伏观察 / 启动确认 / 过热排除”.

- API:
  - `GET /api/stealth/candidates?stage=&min_score=&limit=`
  - `GET /api/stealth/candidates/{symbol}`
  - `POST /api/stealth/scan/run` creates a background scan task. Omit `limit` for a full A-share scan; pass `limit` for development checks.
  - `GET /api/stealth/scan/tasks/latest`
  - `GET /api/stealth/scan/tasks/{task_id}`
  - `POST /api/stealth/observe/{symbol}`
  - `DELETE /api/stealth/observe/{symbol}`
- P0 task flow:
  - the page creates a task instead of waiting for a full-market scan;
  - the task records queued/running/completed/failed status, total/scanned/saved/failed counts, stage counts, message, error, and timestamps;
  - completed tasks persist daily bars, theme memberships, scan results, and an auditable evidence chain.
- Scoring:
  - accumulation: 60/120-day range contraction, volatility compression, controlled volume, MA repair.
  - launch: platform breakout, amount expansion, MA alignment, non-extreme daily move.
  - theme: AKShare concept membership plus active theme overlap.
  - risk penalty: ST, insufficient history, low liquidity, short-term overheating.
- Data source: set `MARKETLENS_HISTORY_PROVIDER=ths_delayed` to use Tonghuashun/iFinD delayed K-lines and `smart_stock_picking` stock universe for the post-market scan; concept membership can temporarily fall back to AKShare via `THS_THEME_FALLBACK_TO_AKSHARE=1`.
- Boundary: output is candidate discovery and observation evidence only. It must not produce buy/sell instructions, target prices, position sizing, or guaranteed returns.
