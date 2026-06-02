from __future__ import annotations

from datetime import datetime, timedelta

from .market_provider import CN_TZ
from .models import AgentStatus


def build_agent_statuses(postgres_ok: bool, redis_ok: bool) -> list[AgentStatus]:
    now = datetime.now(CN_TZ)
    infra_ok = postgres_ok and redis_ok
    data_status = "healthy" if infra_ok else "degraded"
    data_message = "PostgreSQL 与 Redis 可用，真实行情请求由接口实时执行。" if infra_ok else "本地数据库或 Redis 未完全可用。"

    return [
        AgentStatus(
            name="Data Collector Agent",
            purpose="拉取授权或公开开发行情源，写入可引用的行情快照。",
            status=data_status,
            last_run_at=now,
            next_run_at=now + timedelta(minutes=5),
            latest_message=data_message,
            failure_count_24h=0 if infra_ok else 1,
        ),
        AgentStatus(
            name="Data Quality Agent",
            purpose="检查真实行情响应的缺失、延迟、异常值和源状态。",
            status=data_status,
            last_run_at=now,
            next_run_at=now + timedelta(minutes=5),
            latest_message="当前版本不使用本地演示行情作为质量兜底。",
            failure_count_24h=0 if infra_ok else 1,
        ),
        AgentStatus(
            name="Pre-open Agent",
            purpose="基于实时行情、自选股和已接入来源生成盘前参考。",
            status="healthy",
            last_run_at=now,
            next_run_at=now + timedelta(minutes=10),
            latest_message="盘前内容仅从真实行情 bundle 生成。",
            failure_count_24h=0,
        ),
        AgentStatus(
            name="Intraday Radar Agent",
            purpose="记录市场宽度、板块排行和自选股异动，服务盘后回放。",
            status="healthy",
            last_run_at=now,
            next_run_at=now + timedelta(minutes=5),
            latest_message="事件流来自实时行情规则，不读取演示事件。",
            failure_count_24h=0,
        ),
        AgentStatus(
            name="Replay Agent",
            purpose="合并真实行情事件，生成错过盘面的复盘摘要。",
            status="healthy",
            last_run_at=now,
            next_run_at=now + timedelta(minutes=10),
            latest_message="复盘报告由实时事件流即时构建。",
            failure_count_24h=0,
        ),
        AgentStatus(
            name="Compliance Agent",
            purpose="拦截买卖建议、目标价、仓位建议和收益承诺。",
            status="healthy",
            last_run_at=now,
            next_run_at=None,
            latest_message="合规拦截保持实时启用。",
            failure_count_24h=0,
        ),
    ]
