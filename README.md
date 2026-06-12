# MarketLens 盘面助手

A股盘后复盘与信息驱动候选挖掘 SaaS 的可运行实现。当前版本包含 FastAPI 后端、Next.js Web/PWA 前端、Docker PostgreSQL/Redis、免费公开行情/新闻/公告源接入、Agent 状态、合规拦截、盘前 Brief、盘中 Radar、盘后 Replay、自选股中心和基于引用的 AI 问答。产品定位是整理公开信息、复盘盘面和筛选观察候选，不提供买卖、仓位、目标价或收益承诺。

## 本地运行

```bash
npm install
npm run db:up
python -m pip install -r backend/requirements.lock
npm run db:migrate
npm run api
npm run dev
```

打开 `http://127.0.0.1:3000` 查看前端页面。

API 文档在 `http://127.0.0.1:8000/docs`。

本地和 CI 环境使用 `backend/requirements.lock` 保持依赖可复现。需要主动刷新锁定版本时，只编辑更小的直接依赖清单 `backend/requirements.txt`。

## 同花顺本地复盘流程

需要跑盘后复盘流程时，用同花顺/iFinD 模式启动 API：

```bash
npm run db:up
npm run api:ths
npm run dev
```

然后先运行不带全市场扫描的复盘冒烟检查：

```bash
npm run smoke:replay
```

只有在同花顺凭证和数据库性能都足够稳定、可以承受候选扫描后，再运行：

```bash
npm run smoke:replay:scan
```

`api:ths` 默认使用纯同花顺模式，会设置 `THS_HISTORY_FALLBACK_TO_AKSHARE=0` 和 `THS_THEME_FALLBACK_TO_AKSHARE=0`。使用真实 iFinD 访问前，请先设置 `THS_REFRESH_TOKEN` 或 `THS_ACCESS_TOKEN`。如果没有凭证，复盘冒烟检查仍会生成日报，并把同花顺数据源标记为数据缺口。

## 验证

```bash
npm run test:api
npm run build
```

## 架构

- `backend/app/main.py`：FastAPI 路由，覆盖看板、盘前 Brief、盘中 Radar、盘后 Replay、自选股、个股档案、助手、合规拦截和后台 Agent 状态。
- `backend/app/market_provider.py`：实时 A 股行情适配器。当前开发适配器优先读取东方财富，需要时回退到新浪财经实时行情，只有实时源不可用时才返回 `503`。
- `backend/app/history_provider.py`：基于 AKShare 的研究适配器，提供 250 日日线、周线、股票池和概念成分。
- `backend/app/stealth_scanner.py`：长周期候选评分，覆盖潜伏吸筹、启动确认、题材共振和风险扣分。
- `backend/app/stealth_tasks.py`：后台潜伏扫描任务执行器。它创建持久化任务，把扫描放到请求线程之外执行，并更新可轮询进度。
- `backend/app/agent_status.py`：采集、质量、盘前、盘中、盘后和合规任务的 Agent 运行状态。
- `backend/app/compliance.py`：拦截买卖、仓位、目标价、收益承诺和推荐类表达。
- `backend/app/database.py`：PostgreSQL 与 Redis 连接、表结构初始化和服务健康检查。
- `backend/app/repositories.py`：自选股、数据源元信息和助手审计日志的持久化读写。
- `app/` 与 `components/`：Next.js SaaS 界面，包含 PWA manifest、分组左侧导航、图表、时间线、自选股和助手面板。

## 生产替换点

- 商用前，把 `backend/app/market_provider.py` 里的东方财富/新浪开发适配器替换为有授权的数据适配器，覆盖交易所行情、公告、新闻、龙虎榜、资金流和基本面。
- 商用前，把 `backend/app/history_provider.py` 里的 AKShare 研究适配器替换为有授权的历史行情、周线、题材和成分数据。
- PostgreSQL 继续作为产品数据库；只有在行情和事件量确实需要时，再引入 TimescaleDB/ClickHouse。
- 将 Agent 任务迁移到 APScheduler/Celery/Redis 或 Temporal，并把告警接入后台状态端点。
- 将助手接入真实检索层，但保持当前引用和合规契约不变。
- 保持产品边界：只做信息整理，不做投资建议、目标价、仓位建议或交易账户访问。

## 本地数据服务

`docker-compose.yml` 会启动：

- PostgreSQL：`127.0.0.1:5432`，数据库 `qrant_agent`
- Redis：`127.0.0.1:6380`，避免和其他本地 Redis 实例冲突

如果其他本地项目已经占用 `5432`，可以换一个宿主机端口启动服务，并同步调整 `DATABASE_URL`：

```bash
MARKETLENS_POSTGRES_PORT=15432 npm run db:up
DATABASE_URL=postgresql://qrant:qrant_dev@127.0.0.1:15432/qrant_agent npm run db:migrate
DATABASE_URL=postgresql://qrant:qrant_dev@127.0.0.1:15432/qrant_agent npm run api
```

API 启动时会初始化表结构，但不会注入演示行情数据。看板、Brief、Radar、Replay、个股档案和助手回答都来自实时行情响应；当实时源不可用时，API 返回 `503`，不会回退到本地假数据。自选股 CRUD、数据源元信息和助手审计日志会持久化到 PostgreSQL。Redis 用于自选股数量等轻量运行时缓存。

表结构变更放在 `backend/migrations/*.sql`，并通过 `npm run db:migrate` 应用。API 仍保留幂等的启动初始化，方便本地开发；新的生产结构变更应通过 SQL migration 交付。

## 同花顺/iFinD 数据源

默认本地开发使用免费公开源：

```bash
MARKETLENS_MARKET_PROVIDER=free
MARKETLENS_HISTORY_PROVIDER=akshare
MARKETLENS_INFO_PROVIDER=akshare
```

免费源覆盖东方财富/新浪实时行情、AKShare 历史 K 线/题材、AKShare 东方财富个股新闻和沪深京公告。它们适合个人复盘和研究筛选；商用前仍需确认数据来源许可、访问频率和稳定性。

MarketLens 可以优先使用同花顺/iFinD 采集市场快照、历史 K 线、股票池和公告：

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

HTTP 适配器会调用 QuantAPI 的 `get_access_token`、`real_time_quotation`、`cmd_history_quotation`、`smart_stock_picking` 和 `report_query`。它会存储标准化行情字段、OHLCV、公告标题/链接元信息和数据源 id。在接入具体授权的 iFinD 新闻端点之前，新闻仍会作为可见数据缺口展示；公告通过 `report_query` 处理。

## 可选 Tushare 信息源兜底

Tushare Pro 仍可作为非默认的信息源兜底：

```bash
MARKETLENS_INFO_PROVIDER=tushare
TUSHARE_TOKEN=your_token
TUSHARE_API_URL=http://api.tushare.pro
TUSHARE_NEWS_SRC=sina
```

该 provider 调用 Tushare Pro 的 `news` 和 `anns_d`，只存储标题、摘要、来源链接、来源 id 和发布时间，并保持现有合规边界不变。

## 一键盘后复盘

使用 `POST /api/admin/jobs/run/post_market_replay`，或点击“数据状态 → 一键盘后复盘”，可以运行 MVP 收盘闭环：

- 采集盘后市场快照；
- 收集新闻和公告；
- 运行有边界的潜伏扫描；
- 快照观察日志；
- 重新生成每日跟踪报告。

默认扫描范围会刻意限制，避免本地手动运行时被全 A 扫描阻塞：

```bash
MARKETLENS_POST_MARKET_ENABLE_SCAN=1
MARKETLENS_POST_MARKET_SCAN_LIMIT=500
MARKETLENS_POST_MARKET_SCAN_OFFSET=0
```

当数据库和数据源都足够稳定、可以承受全市场扫描后，再设置 `MARKETLENS_POST_MARKET_SCAN_LIMIT=full`。

## 潜伏发现

`#stealth` 页面提供只用于研究的候选扫描器，覆盖“潜伏观察 / 启动确认 / 过热排除”。

- API:
  - `GET /api/stealth/candidates?stage=&min_score=&limit=`
  - `GET /api/stealth/candidates/{symbol}`
  - `POST /api/stealth/scan/run` 创建后台扫描任务。不传 `limit` 表示全 A 扫描；开发检查时传入 `limit`。
  - `GET /api/stealth/scan/tasks/latest`
  - `GET /api/stealth/scan/tasks/{task_id}`
  - `POST /api/stealth/observe/{symbol}`
  - `DELETE /api/stealth/observe/{symbol}`
- P0 任务流：
  - 页面创建任务，不直接等待全市场扫描完成；
  - 任务持久化请求参数、是否包含自选股、worker id 和 lease 过期时间，让多个应用实例通过 PostgreSQL 领取工作，而不是只依赖进程内存；
  - 任务记录 queued/running/completed/failed 状态、total/scanned/saved/failed 计数、阶段计数、消息、错误和时间戳；
  - 完成后的任务会持久化日线、题材成分、扫描结果和可审计证据链。
- 评分：
  - 潜伏吸筹：60/120 日区间收敛、波动压缩、量能受控、均线修复。
  - 启动确认：平台突破、成交额放大、均线排列、非极端日涨跌。
  - 题材共振：AKShare 概念成分叠加活跃题材重合。
  - 风险扣分：ST、历史不足、流动性偏低、短期过热。
- 数据源：设置 `MARKETLENS_HISTORY_PROVIDER=ths_delayed` 后，盘后扫描会使用同花顺/iFinD 延迟 K 线和 `smart_stock_picking` 股票池；概念成分可通过 `THS_THEME_FALLBACK_TO_AKSHARE=1` 临时回退到 AKShare。
- 边界：输出只包含候选发现和观察证据，不能生成买卖指令、目标价、仓位建议或收益承诺。
