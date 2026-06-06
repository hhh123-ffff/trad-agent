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
            name="PostMarket Coordinator",
            purpose="按固定步骤编排盘后数据、研究、观察与合规流程。",
            status=data_status,
            last_run_at=now,
            next_run_at=now + timedelta(days=1),
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
            name="Announcement Analyst Agent",
            purpose="只读取结构化公告与新闻摘要，整理重要性、关联标的和数据缺口。",
            status="healthy",
            last_run_at=now,
            next_run_at=now + timedelta(days=1),
            latest_message="公告正文不会直接发送给模型。",
            failure_count_24h=0,
        ),
        AgentStatus(
            name="Candidate Research Agent",
            purpose="基于确定性筛选结果解释规则命中、证据和风险缺口。",
            status="healthy",
            last_run_at=now,
            next_run_at=now + timedelta(days=1),
            latest_message="Agent 不修改策略阈值，也不输出买卖建议。",
            failure_count_24h=0,
        ),
        AgentStatus(
            name="Observation Manager Agent",
            purpose="受控更新当前候选观察项，删除动作进入人工审批。",
            status="healthy",
            last_run_at=now,
            next_run_at=now + timedelta(days=1),
            latest_message="自动写入仅限当前确定性候选。",
            failure_count_24h=0,
        ),
        AgentStatus(
            name="Report Editor Agent",
            purpose="把确定性日报与各 Agent 结构化输出整理为盘后研究简报。",
            status="healthy",
            last_run_at=now,
            next_run_at=now + timedelta(days=1),
            latest_message="模型失败时保留确定性日报作为回退。",
            failure_count_24h=0,
        ),
        AgentStatus(
            name="Compliance Guard",
            purpose="拦截买卖建议、目标价、仓位建议和收益承诺。",
            status="healthy",
            last_run_at=now,
            next_run_at=None,
            latest_message="合规拦截保持实时启用。",
            failure_count_24h=0,
        ),
    ]
