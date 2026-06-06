# A股每日使用闭环设计

## 目标

把现有盘后复盘能力升级为可以稳定每天运行、失败后可定位和可恢复的操作闭环。系统继续以事实整理、策略筛选和风险提示为边界，不输出买卖建议、目标价、仓位建议或收益承诺。

本阶段只解决每日运行稳定性和可观察性。策略回测、命中率评估和更大范围的前端改版放到后续阶段。

## 成功标准

- 一个盘后编排任务依次完成收盘快照、公告采集、股票扫描、观察池日志、确定性日报和 Agent 简报。
- 任一步骤失败时，后续可独立运行的步骤继续执行，最终生成基于可用数据的日报。
- 每个步骤记录状态、开始/结束时间、耗时、错误、重试次数和结果摘要。
- 网络或临时数据源错误可以自动重试；缺少 Token、配置错误和数据契约错误不自动重试。
- 数据过期或缺失时，日报、任务详情和通知中心都明确展示数据缺口。
- 周末和非交易日不会由调度器自动生成新的交易日报。
- 数据状态页可以查看流水线详情、重跑失败步骤和确认当天闭环状态。

## 范围

### 本阶段包含

- 盘后编排流水线和步骤级持久化。
- 失败分类、有限重试和单步骤重跑。
- 数据新鲜度检查。
- 应用内通知中心。
- 调度交易日保护。
- 数据状态页的运行详情和失败恢复入口。
- API、服务和前端的自动化测试。

### 本阶段不包含

- 短信、邮件、微信或第三方告警渠道。
- 分钟线接入和策略回测。
- 同花顺 Token 申请或商业数据授权。
- 分布式任务队列、Celery 或 Temporal。
- 自动交易和投资建议。

## 架构

### 编排模型

保留现有 `post_market_replay` 任务作为用户和调度器的统一入口。该任务按固定顺序运行以下步骤：

1. `close_snapshot`
2. `collect_information`
3. `stealth_scan`
4. `observation_journal`
5. `daily_report`
6. `agent_post_market`

编排器负责顺序、依赖、重试和最终状态汇总。各步骤仍调用现有服务函数，不复制业务逻辑。

步骤依赖规则：

- `daily_report` 始终执行，并基于当前可用数据生成报告。
- `agent_post_market` 在确定性日报生成后执行；模型未配置时保存确定性回退。
- `stealth_scan` 失败不阻止观察日志和日报生成。
- `collect_information` 和 `close_snapshot` 失败会写入日报数据缺口。

### 持久化模型

继续使用 `job_runs` 保存顶层任务运行。新增 `job_run_steps`：

- `id`
- `job_run_id`
- `step_name`
- `status`: `pending | running | completed | degraded | failed | skipped`
- `attempt`
- `started_at`
- `finished_at`
- `duration_ms`
- `result_scope`
- `error_code`
- `error`
- `retryable`

新增 `app_notifications`：

- `id`
- `notification_type`: `pipeline_completed | pipeline_degraded | pipeline_failed | data_stale`
- `severity`: `info | warning | critical`
- `title`
- `message`
- `related_job_run_id`
- `metadata`
- `read_at`
- `created_at`

通知只记录应用内状态，不主动向外部渠道发送信息。

## 错误分类与重试

错误统一分类为：

- `temporary_provider_error`: 超时、连接失败、临时 5xx，可重试。
- `rate_limit`: 限流，可重试并延迟。
- `missing_credentials`: 缺少 Token，不重试。
- `configuration_error`: 配置值错误，不重试。
- `data_contract_error`: 返回结构不可解析，不重试并要求人工检查。
- `storage_error`: PostgreSQL/Redis 写入失败，按有限次数重试。
- `unknown_error`: 默认不自动反复重试。

默认重试策略：

- 每个可重试步骤最多执行 3 次。
- 使用短退避间隔，避免本地任务长时间阻塞。
- 每次尝试独立记录。
- 手动单步骤重跑创建新的步骤尝试记录，不覆盖历史。

## 数据新鲜度

闭环完成前执行新鲜度检查：

- 最新市场快照日期是否为目标交易日。
- 最新日线交易日是否为目标交易日或最近有效交易日。
- 公告查询窗口是否覆盖目标交易日。
- 确定性日报是否基于目标交易日生成。
- Agent 简报是否引用最新确定性日报。

结果分为 `fresh | stale | missing`，并写入：

- 顶层任务 `affected_scope.data_freshness`
- 每日报告“数据质量与缺口”板块
- 应用内通知
- 数据状态页

## 交易日保护

手动任务允许在任意日期运行，方便补跑和测试。

自动调度任务仅在以下条件满足时运行：

- `MARKETLENS_ENABLE_SCHEDULER=1`
- 当前日期为周一至周五
- 交易日判断未明确返回休市

第一版交易日判断使用工作日加最近行情日期保护。若无法确认交易日，任务不静默跳过，而是创建 `skipped` 运行记录并说明原因。

## API 设计

保留现有入口：

- `POST /api/admin/jobs/run/post_market_replay`
- `GET /api/admin/jobs/runs`

兼容扩展：

- `GET /api/admin/jobs/runs/{run_id}`：返回顶层运行和步骤详情。
- `POST /api/admin/jobs/runs/{run_id}/steps/{step_name}/rerun`：重跑指定失败或降级步骤。
- `GET /api/admin/notifications`：读取应用内通知。
- `POST /api/admin/notifications/{notification_id}/read`：标记已读。

不改变已有 `JobRun` 字段语义，新增步骤详情通过独立模型返回。

## 前端设计

数据状态页增加“今日闭环”主要工作区：

- 顶部显示目标交易日、整体状态、完成时间和数据新鲜度。
- 中部按顺序展示六个步骤，每个步骤显示状态、耗时、尝试次数和结果摘要。
- 失败或降级步骤展示错误分类、下一步提示和重跑按钮。
- 页面右侧或下方展示通知中心，可筛选未读、警告和严重通知。

状态颜色保持一致：

- 完成：松绿
- 运行中：信号蓝
- 降级/跳过：琥珀
- 失败/严重：风险红

移动端使用单列步骤时间线，不新增横向溢出。

## 状态汇总

顶层流水线状态规则：

- 所有必需步骤完成：`completed`
- 日报完成但任一数据步骤失败、降级或跳过：`degraded`
- 日报无法生成或存储失败：`failed`

现有 `JobRun.status` 当前没有 `degraded` 和 `skipped`。本阶段扩展这两个状态，并保持前端对旧状态兼容。

## 测试与验收

### 后端测试

- 完整成功：六个步骤完成，顶层状态为 `completed`。
- 无同花顺 Token：行情与公告步骤标记 `failed` 或 `skipped`，日报完成，顶层状态为 `degraded`。
- 临时接口失败：步骤自动重试后成功，记录尝试次数。
- 永久配置失败：不重试，展示处理提示。
- 日报生成失败：顶层状态为 `failed`。
- 单步骤重跑：只执行目标步骤，并保留原始运行历史。
- 周末自动调度：生成明确的 `skipped` 记录，不执行数据步骤。
- 新鲜度过期：生成 `data_stale` 通知并写入日报缺口。

### 前端测试

- 完整成功、降级、失败、运行中和跳过状态均正常展示。
- 重跑按钮只在可恢复步骤显示。
- 通知可读取和标记已读。
- 桌面和移动端无重叠或横向溢出。

### 手动验收

1. 在无同花顺 Token 状态运行一键盘后复盘。
2. 确认日报仍有六个板块，并明确展示行情和公告缺口。
3. 在数据状态页查看步骤级失败原因和下一步提示。
4. 配置可用数据源后重跑失败步骤。
5. 确认整体状态和通知更新，历史运行记录仍保留。

## 后续阶段接口

本阶段沉淀的步骤级运行记录和新鲜度结果，将在第二阶段作为回测数据质量门槛，在第三阶段作为盘后工作台的主要状态来源。
