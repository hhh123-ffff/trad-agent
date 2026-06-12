# 观澜

[![CI](https://github.com/hhh123-ffff/trad-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/hhh123-ffff/trad-agent/actions/workflows/ci.yml)
![Next.js](https://img.shields.io/badge/Next.js-16-black)
![FastAPI](https://img.shields.io/badge/FastAPI-Python-009688)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-336791)

观澜取“观其波澜，辨其来势”之意，是一个面向 A 股盘后复盘、公开信息整理与候选观察的研究工作台。它把行情、新闻、公告、题材、观察池和 AI 问答放进同一个可审计流程，帮助用户复盘市场结构、发现值得继续跟踪的线索。

> 观澜只做公开/授权信息整理、盘面复盘和研究候选筛选，不提供买卖指令、仓位建议、目标价、收益承诺或交易账户操作。

## 项目概览

| 维度 | 内容 |
| --- | --- |
| 产品形态 | A 股盘前 Brief、盘中 Radar、盘后 Replay、潜伏发现、自选股中心、引用式 AI 问答 |
| 前端 | Next.js 16、React 19、Tailwind CSS、Recharts、PWA manifest |
| 后端 | FastAPI、Pydantic、PostgreSQL、Redis、后台任务状态与合规拦截 |
| 默认数据源 | 东方财富/新浪实时行情、AKShare 历史 K 线/题材、AKShare 新闻公告 |
| 可选数据源 | 同花顺/iFinD、Tushare Pro，作为非默认的授权或兜底接入 |
| 工程治理 | GitHub Actions、中文 PR 模板、`main` 分支保护、可复现 Python 依赖锁 |

## 核心能力

| 模块 | 作用 | 交付结果 |
| --- | --- | --- |
| 盘前 Brief | 汇总隔夜与开盘前关注点 | 盘前参考、数据源状态、风险提醒 |
| 盘中 Radar | 跟踪实时行情和板块变化 | 市场温度、指数表现、板块轮动、盘中事件 |
| 盘后 Replay | 一键运行盘后收盘闭环 | 市场快照、新闻公告、观察日志、每日跟踪报告 |
| 潜伏发现 | 扫描长期候选与启动确认 | 候选分层、评分解释、短线/中长线证据链 |
| 自选股中心 | 管理观察标的和标签 | 持久化观察池、候选转观察、跟踪摘要 |
| AI 问答 | 基于引用回答市场问题 | 可追溯回答、合规拦截、审计日志 |

## 快速开始

```bash
npm install
npm run db:up
python -m pip install -r backend/requirements.lock
npm run db:migrate
npm run api
npm run dev
```

打开前端：

```text
http://127.0.0.1:3000
```

查看 API 文档：

```text
http://127.0.0.1:8000/docs
```

本地和 CI 环境使用 `backend/requirements.lock` 保持依赖可复现。需要刷新 Python 依赖版本时，先编辑 `backend/requirements.txt`，再重新生成锁定文件。

## 本地数据服务

`docker-compose.yml` 会启动项目所需的数据服务：

| 服务 | 默认地址 | 说明 |
| --- | --- | --- |
| PostgreSQL | `127.0.0.1:5432` | 数据库名 `qrant_agent` |
| Redis | `127.0.0.1:6380` | 用于轻量缓存、任务锁和运行态信息 |

如果本机 `5432` 已被其他项目占用，可以切换到隔离端口：

```bash
MARKETLENS_POSTGRES_PORT=15432 npm run db:up
DATABASE_URL=postgresql://qrant:qrant_dev@127.0.0.1:15432/qrant_agent npm run db:migrate
DATABASE_URL=postgresql://qrant:qrant_dev@127.0.0.1:15432/qrant_agent npm run api
```

API 启动时会初始化基础表结构，但不会注入演示行情数据。看板、Brief、Radar、Replay、个股档案和助手回答都来自实时或公开数据源；当实时源不可用时，API 返回 `503`，不会回退到本地假数据。

## 数据源策略

默认本地开发使用免费公开源：

```bash
MARKETLENS_MARKET_PROVIDER=free
MARKETLENS_HISTORY_PROVIDER=akshare
MARKETLENS_INFO_PROVIDER=akshare
```

免费源覆盖：

- 东方财富实时行情；
- 新浪财经实时行情兜底；
- AKShare 历史 K 线、周线、股票池和题材成分；
- AKShare 东方财富个股新闻和沪深京公告。

免费公开源适合个人复盘、功能开发和研究筛选。商用前必须确认数据来源许可、访问频率、稳定性和合规要求，并替换为正式授权数据源。

### 同花顺/iFinD 模式

需要跑同花顺/iFinD 复盘流程时，可以使用：

```bash
npm run db:up
npm run api:ths
npm run dev
```

然后先运行不带全市场扫描的冒烟检查：

```bash
npm run smoke:replay
```

确认凭证、数据库和数据源都稳定后，再运行候选扫描版：

```bash
npm run smoke:replay:scan
```

同花顺/iFinD 相关配置：

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

`api:ths` 默认使用纯同花顺模式，会设置 `THS_HISTORY_FALLBACK_TO_AKSHARE=0` 和 `THS_THEME_FALLBACK_TO_AKSHARE=0`。使用真实 iFinD 访问前，请先设置 `THS_REFRESH_TOKEN` 或 `THS_ACCESS_TOKEN`。

### Tushare 兜底

Tushare Pro 仍可作为非默认的信息源兜底：

```bash
MARKETLENS_INFO_PROVIDER=tushare
TUSHARE_TOKEN=your_token
TUSHARE_API_URL=http://api.tushare.pro
TUSHARE_NEWS_SRC=sina
```

该 provider 只存储标题、摘要、来源链接、来源 id 和发布时间，并保持现有合规边界不变。

## 盘后复盘闭环

使用 `POST /api/admin/jobs/run/post_market_replay`，或在前端点击“数据状态 -> 一键盘后复盘”，可以运行 MVP 收盘闭环：

1. 采集盘后市场快照；
2. 收集新闻和公告；
3. 运行有边界的潜伏扫描；
4. 快照观察日志；
5. 重新生成每日跟踪报告。

默认扫描范围会刻意限制，避免本地手动运行时被全 A 扫描阻塞：

```bash
MARKETLENS_POST_MARKET_ENABLE_SCAN=1
MARKETLENS_POST_MARKET_SCAN_LIMIT=500
MARKETLENS_POST_MARKET_SCAN_OFFSET=0
```

当数据库和数据源都足够稳定、可以承受全市场扫描后，再设置：

```bash
MARKETLENS_POST_MARKET_SCAN_LIMIT=full
```

## 潜伏发现

`#stealth` 页面提供只用于研究的候选扫描器，覆盖“潜伏观察 / 启动确认 / 过热排除”。

| 能力 | 说明 |
| --- | --- |
| 后台扫描 | `POST /api/stealth/scan/run` 创建任务，任务进度可轮询 |
| 任务持久化 | 请求参数、worker、lease、计数、状态、错误和时间戳写入 PostgreSQL |
| 证据链 | 持久化日线、题材成分、扫描结果和候选解释 |
| 观察池 | 支持 `POST /api/stealth/observe/{symbol}` 和 `DELETE /api/stealth/observe/{symbol}` |

评分维度：

- 潜伏吸筹：60/120 日区间收敛、波动压缩、量能受控、均线修复；
- 启动确认：平台突破、成交额放大、均线排列、非极端日涨跌；
- 题材共振：AKShare 概念成分叠加活跃题材重合；
- 风险扣分：ST、历史不足、流动性偏低、短期过热。

输出只包含候选发现和观察证据，不能生成买卖指令、目标价、仓位建议或收益承诺。

## 系统架构

| 路径 | 职责 |
| --- | --- |
| `app/` | Next.js App Router 入口、页面 metadata 和全局样式 |
| `components/` | 观澜工作台界面、导航、图表、时间线、自选股和助手面板 |
| `backend/app/main.py` | FastAPI 路由，覆盖看板、Brief、Radar、Replay、自选股、助手和后台任务 |
| `backend/app/market_provider.py` | 东方财富/新浪实时行情适配器 |
| `backend/app/history_provider.py` | AKShare 历史行情、周线、股票池和题材成分适配器 |
| `backend/app/data_providers.py` | 免费源、同花顺/iFinD、Tushare 的 provider 路由 |
| `backend/app/stealth_scanner.py` | 长周期候选评分和证据解释 |
| `backend/app/stealth_tasks.py` | 后台潜伏扫描任务执行器 |
| `backend/app/repositories.py` | 自选股、数据源元信息和助手审计日志 |
| `backend/migrations/` | PostgreSQL 结构变更 SQL |

## 验证

常用检查：

```bash
npm run build
DATABASE_URL=postgresql://qrant:qrant_dev@127.0.0.1:15432/qrant_agent \
REDIS_URL=redis://127.0.0.1:6380/0 \
./.venv/bin/python -m pytest backend/tests -q
```

`npm run test:api` 依赖当前 shell 能直接找到 `pytest`。如果本机没有全局 `pytest`，优先使用仓库 `.venv` 的 Python 运行测试。

## 生产替换点

- 将东方财富/新浪开发适配器替换为有授权的数据适配器，覆盖交易所行情、公告、新闻、龙虎榜、资金流和基本面；
- 将 AKShare 研究适配器替换为有授权的历史行情、周线、题材和成分数据；
- PostgreSQL 继续作为产品数据库，只有在行情和事件量确实需要时，再引入 TimescaleDB 或 ClickHouse；
- 将 Agent 任务迁移到 APScheduler、Celery、Redis 队列或 Temporal，并把告警接入后台状态端点；
- 将助手接入真实检索层，但保持引用展示、合规拦截和审计日志契约不变。

## 工程治理

| 事项 | 状态 |
| --- | --- |
| CI | `.github/workflows/ci.yml` 执行后端测试、Python 编译检查和前端构建 |
| PR 模板 | `.github/pull_request_template.md` 使用中文变更、验证、数据源影响和合规边界清单 |
| 分支保护 | `docs/operations/branch-protection.md` 记录 `main` 分支保护与必需状态检查 |
| 依赖锁 | `backend/requirements.lock` 固定本地和 CI 使用的 Python 依赖版本 |

## 命名与兼容

项目对外名称统一为“观澜”，包名为 `guanlan-research-workbench`，API 标题为“观澜 API”。为避免破坏已有本地环境和部署脚本，环境变量暂时继续沿用 `MARKETLENS_` 前缀；如果后续需要迁移到 `GUANLAN_`，建议单独开兼容迁移 PR。
